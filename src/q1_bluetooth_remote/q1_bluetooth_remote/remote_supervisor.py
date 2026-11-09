#!/usr/bin/env python3

import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from aimdk_msgs.msg import AsrResult, CommonRequest, TtsPriorityLevel, TtsStatus
from aimdk_msgs.srv import PlayTts, StopTtsTraceId

from q1_bluetooth_remote.input_devices import find_profile_inputs
from q1_bluetooth_remote.remote_profiles import (
    get_profile,
    load_store,
    save_store,
)

CONNECT_COMMANDS = {
    "启动R1遥控",
    "启动R1遥控器",
}
BIND_COMMANDS = {
    "绑定蓝牙遥控器",
    "绑定遥控器",
    "绑定蓝牙手柄",
    "绑定手柄",
}
CONFIRM_COMMANDS = {"确认", "确认连接", "确定", "是"}
CANCEL_COMMANDS = {"取消", "取消绑定", "取消连接"}


class RemoteSupervisor(Node):
    def __init__(self):
        super().__init__("remote_supervisor")
        self.profile = get_profile(load_store())
        self.controller_execute = bool(
            self.declare_parameter("controller_execute", True).value
        )
        self.workspace = Path(
            self.declare_parameter(
                "workspace_root", os.environ.get("Q1_WORKSPACE_ROOT", str(Path.cwd()))
            ).value
        )
        self.controller_process = None
        self.pending_bind_address = None
        self.busy = False
        self.state_lock = threading.Lock()
        self.recent_events = set()
        self.recent_event_order = []
        self.suppress_cloud_tts_until = 0.0
        self.stopped_trace_ids = set()

        self.create_subscription(
            AsrResult,
            "/aima/agent/asr_result",
            self._on_asr_result,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            TtsStatus,
            "/interaction/tts_status",
            self._on_tts_status,
            qos_profile_sensor_data,
        )
        self.tts_client = self.create_client(
            PlayTts, "/aimdk_5Fmsgs/srv/PlayTts"
        )
        self.stop_tts_client = self.create_client(
            StopTtsTraceId, "/aimdk_5Fmsgs/srv/StopTtsTraceId"
        )
        self.create_timer(1.0, self._monitor_controller)
        self.get_logger().info(
            f"语音监督服务已启动；目标：{self.profile['name']} "
            f"（{self.profile['address']}）；连接与绑定使用独立指令"
        )

    def _speak(self, text):
        self.get_logger().info(f"语音提示：{text}")
        if not self.tts_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warning("PlayTts 服务不可用")
            return
        request = PlayTts.Request()
        request.header = CommonRequest()
        request.header.header.stamp = self.get_clock().now().to_msg()
        request.tts_req.text = text
        request.tts_req.priority_level.value = TtsPriorityLevel.INTERACTION_L6
        request.tts_req.priority_weight = 0
        request.tts_req.domain = "remote_supervisor"
        request.tts_req.trace_id = f"remote_supervisor_{time.monotonic_ns()}"
        request.tts_req.is_interrupted = True
        self.tts_client.call_async(request)

    def _on_tts_status(self, msg):
        if time.monotonic() > self.suppress_cloud_tts_until:
            return
        if msg.domain in {"remote_supervisor", "bluetooth_walk_control"}:
            return
        if msg.trace_id.startswith(("remote_supervisor_", "remote_")):
            return
        if not msg.trace_id or msg.trace_id in self.stopped_trace_ids:
            return
        if msg.tts_status.value not in (1, 2, 6):
            return
        self.stopped_trace_ids.add(msg.trace_id)
        if len(self.stopped_trace_ids) > 100:
            self.stopped_trace_ids.clear()
        request = StopTtsTraceId.Request()
        request.header = CommonRequest()
        request.header.header.stamp = self.get_clock().now().to_msg()
        request.trace_id = msg.trace_id
        self.stop_tts_client.call_async(request)
        self.get_logger().warning(
            f"已拦截自定义指令窗口内的其他播报：{msg.text}；trace={msg.trace_id}"
        )

    def _on_asr_result(self, msg):
        if not msg.is_final:
            return
        command = "".join(msg.text.split()).strip("，。！？!?,. ").upper()
        if command not in (
            CONNECT_COMMANDS | BIND_COMMANDS | CONFIRM_COMMANDS | CANCEL_COMMANDS
        ):
            return
        self.suppress_cloud_tts_until = time.monotonic() + 12.0
        if msg.event_id:
            if msg.event_id in self.recent_events:
                return
            self.recent_events.add(msg.event_id)
            self.recent_event_order.append(msg.event_id)
            if len(self.recent_event_order) > 32:
                self.recent_events.discard(self.recent_event_order.pop(0))

        if command in CONNECT_COMMANDS:
            self._start_worker(self._connect_and_start)
        elif command in BIND_COMMANDS:
            self._start_worker(self._prepare_binding)
        elif command in CONFIRM_COMMANDS:
            self._confirm_binding()
        else:
            self.pending_bind_address = None
            self._speak("已取消绑定操作")

    def _start_worker(self, target):
        with self.state_lock:
            if self.busy:
                self.get_logger().warning("正在处理其他蓝牙操作，忽略重复指令")
                return
            self.busy = True
        threading.Thread(target=target, daemon=True).start()

    def _finish_worker(self):
        with self.state_lock:
            self.busy = False

    def _device_info(self, address):
        result = subprocess.run(
            ["bluetoothctl", "info", address],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout

    @staticmethod
    def _is_paired(info):
        return "Paired: yes" in info or "Bonded: yes" in info

    @staticmethod
    def _is_connected(info):
        return "Connected: yes" in info

    def _connect_and_start(self):
        try:
            address = self.profile["address"]
            if self.controller_process and self.controller_process.poll() is None:
                self._speak("遥控器已经连接并运行")
                return
            info = self._device_info(address)
            if not self._is_paired(info):
                self._speak("R1 遥控器尚未绑定，请先说，绑定蓝牙遥控器")
                return

            self._speak(f"正在连接已绑定的 {self.profile['name']} 遥控器")
            if not self._is_connected(info):
                subprocess.run(
                    ["bluetoothctl", "connect", address],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
            if not self._is_connected(self._device_info(address)):
                raise RuntimeError("已绑定遥控器连接失败")

            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                try:
                    find_profile_inputs(self.profile)
                    break
                except RuntimeError:
                    time.sleep(0.5)
            else:
                raise RuntimeError("蓝牙已连接，但 HID 输入节点未就绪")

            command = [
                str(self.workspace / "scripts" / "run_walk_control.sh"),
                "--ros-args",
                "-p",
                f"execute:={'true' if self.controller_execute else 'false'}",
            ]
            self.get_logger().info(f"启动遥控控制器：{' '.join(command)}")
            process = subprocess.Popen(
                command,
                cwd=self.workspace,
                start_new_session=True,
            )
            self.controller_process = process
            time.sleep(2.0)
            if process.poll() is not None:
                raise RuntimeError(f"控制器启动后提前退出，exit={process.returncode}")
            self._speak("遥控器已连接并启动")
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            self.get_logger().error(str(error))
            self._speak("遥控器连接或启动失败")
        finally:
            self._finish_worker()

    def _prepare_binding(self):
        try:
            address = self.profile["address"]
            if self._is_paired(self._device_info(address)):
                self._speak("R1 遥控器已经绑定，无需重复绑定")
                return

            self._speak("正在搜索可用的 R1 遥控器")
            addresses = self._scan_for_r1()
            if not addresses:
                self._speak("没有搜索到可用的 R1 遥控器")
                return
            address = address if address in addresses else addresses[0]
            self._remember_address(address)
            self.pending_bind_address = address
            self._speak("搜索到可用的 R1 遥控器，是否连接？请说，确认连接")
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            self.get_logger().error(str(error))
            self._speak("搜索或绑定准备失败")
        finally:
            self._finish_worker()

    def _scan_for_r1(self):
        self._bluetooth_session((("scan on", 10.0), ("scan off", 0.0)))
        result = subprocess.run(
            ["bluetoothctl", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return re.findall(
            r"Device ([0-9A-Fa-f:]+) Magicsee R1(?:\s|$)",
            result.stdout,
            flags=re.MULTILINE,
        )

    def _remember_address(self, address):
        if address == self.profile["address"]:
            return
        store = load_store()
        profile = dict(self.profile)
        profile.pop("address", None)
        store["profiles"][address] = profile
        store["active_address"] = address
        save_store(store)
        self.profile = get_profile(store, address)
        self.get_logger().info(f"已记忆新的 R1 地址：{address}")

    def _confirm_binding(self):
        address = self.pending_bind_address
        if not address:
            self._speak("当前没有需要确认的 R1 绑定连接")
            return
        self.pending_bind_address = None
        self._start_worker(lambda: self._bind_and_connect(address))

    def _bind_and_connect(self, address):
        try:
            self._speak("正在绑定并连接 R1 遥控器")
            self._bluetooth_session(
                (
                    ("agent NoInputNoOutput", 0.2),
                    ("default-agent", 0.2),
                    (f"pair {address}", 15.0),
                    (f"trust {address}", 1.0),
                    (f"connect {address}", 15.0),
                )
            )
            info = self._device_info(address)
            if not self._is_paired(info) or not self._is_connected(info):
                raise RuntimeError("配对或连接未成功")
            self._speak("R1 绑定并连接成功；之后可以说，启动R1遥控，即可开始遥控")
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            self.get_logger().error(str(error))
            self._speak("R1 绑定或连接失败")
        finally:
            self._finish_worker()

    @staticmethod
    def _bluetooth_session(commands):
        process = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            for command, delay in commands:
                process.stdin.write(command + "\n")
                process.stdin.flush()
                time.sleep(delay)
            process.stdin.write("quit\n")
            process.stdin.flush()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)

    def _monitor_controller(self):
        process = self.controller_process
        if process is None:
            return
        return_code = process.poll()
        if return_code is None:
            return
        self.get_logger().warning(f"遥控控制器已退出，exit={return_code}")
        self.controller_process = None

    def stop_controller(self):
        self.pending_bind_address = None
        process = self.controller_process
        if process is None or process.poll() is not None:
            return
        self.get_logger().info("正在停止遥控控制器")
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=8.0)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
        self.controller_process = None


def main(args=None):
    rclpy.init(args=args)
    node = RemoteSupervisor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop_controller()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
