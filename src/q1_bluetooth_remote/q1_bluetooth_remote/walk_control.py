#!/usr/bin/env python3

from dataclasses import dataclass
import os
import select
import signal
import struct
import threading
import time

import rclpy
from rclpy.node import Node

from aimdk_msgs.msg import (
    CommonRequest,
    CommonState,
    McActionCommand,
    McLocomotionVelocity,
    MessageHeader,
    RequestHeader,
    TtsPriorityLevel,
)
from aimdk_msgs.srv import (
    GetCurrentInputSource,
    GetMcAction,
    PlayTts,
    SetMcAction,
    SetMcInputSource,
    SetMcPresetMotion,
)
from common.mc_action_switcher import McActionSwitchOptions, McActionSwitcher

from q1_bluetooth_remote.action_gestures import (
    GROUND_ACTIONS,
    STANDING_ACTIONS,
    LongPressActionState,
    PressHoldActionState,
)
from q1_bluetooth_remote.input_devices import find_profile_inputs
from q1_bluetooth_remote.remote_profiles import get_profile, load_store

EV_KEY = 0x01
EV_ABS = 0x03
EVENT_STRUCT = struct.Struct("@qqHHi")
DEFAULT_KEYMAP = {
    "forward": 103,
    "backward": 108,
    "turn_left": 105,
    "turn_right": 106,
    "lateral_right": 353,
    "lateral_left": 158,
}


@dataclass(frozen=True)
class VelocityCommand:
    forward: float = 0.0
    lateral: float = 0.0
    angular: float = 0.0


class ButtonState:
    def __init__(
        self, forward_speed, lateral_speed, angular_speed, keymap=None, axismap=None
    ):
        self.forward_speed = forward_speed
        self.lateral_speed = lateral_speed
        self.angular_speed = angular_speed
        self.keymap = dict(keymap or DEFAULT_KEYMAP)
        self.axismap = {
            int(code): config for code, config in (axismap or {}).items()
        }
        self.pressed = {code: False for code in self.keymap.values()}
        self.axis_pressed = set()
        self.last_event_time = time.monotonic()

    def handle_event(self, code, value, now=None):
        if code not in self.pressed:
            return None
        now = time.monotonic() if now is None else now
        self.last_event_time = now
        pressed = value != 0
        if self.pressed[code] == pressed:
            return None
        self.pressed[code] = pressed
        return self.target()

    def handle_axis(self, code, value, now=None):
        if code not in self.axismap:
            return None
        now = time.monotonic() if now is None else now
        self.last_event_time = now
        config = self.axismap[code]
        previous = set(self.axis_pressed)
        self.axis_pressed.discard(config["negative_role"])
        self.axis_pressed.discard(config["positive_role"])
        if value == config["negative_value"]:
            self.axis_pressed.add(config["negative_role"])
        elif value == config["positive_value"]:
            self.axis_pressed.add(config["positive_role"])
        if self.axis_pressed == previous:
            return None
        return self.target()

    def _pressed(self, role):
        code = self.keymap.get(role)
        return (code is not None and self.pressed[code]) or role in self.axis_pressed

    def target(self):
        forward = (
            int(self._pressed("forward")) - int(self._pressed("backward"))
        ) * self.forward_speed
        angular = (
            int(self._pressed("turn_left")) - int(self._pressed("turn_right"))
        ) * self.angular_speed
        lateral = (
            int(self._pressed("lateral_left"))
            - int(self._pressed("lateral_right"))
        ) * self.lateral_speed
        return VelocityCommand(forward, lateral, angular)

    def clear(self):
        self.pressed = {code: False for code in self.pressed}
        self.axis_pressed.clear()

    def expire_if_stale(self, timeout, now=None):
        now = time.monotonic() if now is None else now
        if not any(self.pressed.values()) and not self.axis_pressed:
            return False
        if now - self.last_event_time < timeout:
            return False
        self.clear()
        return True


class VelocityRamp:
    def __init__(self, forward_rate, lateral_rate, angular_rate):
        self.forward_rate = forward_rate
        self.lateral_rate = lateral_rate
        self.angular_rate = angular_rate
        self.current = VelocityCommand()

    @staticmethod
    def _step(current, target, max_change):
        if target == 0.0:
            return 0.0
        change = target - current
        if abs(change) <= max_change:
            return target
        return current + max_change if change > 0 else current - max_change

    def advance(self, target, elapsed):
        self.current = VelocityCommand(
            self._step(
                self.current.forward, target.forward, self.forward_rate * elapsed
            ),
            self._step(
                self.current.lateral, target.lateral, self.lateral_rate * elapsed
            ),
            self._step(
                self.current.angular, target.angular, self.angular_rate * elapsed
            ),
        )
        return self.current

    def clear(self):
        self.current = VelocityCommand()


class WalkControl(Node):
    def __init__(self):
        super().__init__("bluetooth_walk_control")
        self.execute = bool(self.declare_parameter("execute", False).value)
        self.requested_device = str(self.declare_parameter("device", "").value)
        remote_address = str(self.declare_parameter("remote_address", "").value)
        self.profile = get_profile(load_store(), remote_address)
        self.input_source = str(
            self.declare_parameter("input_source", "").value
        ) or self.profile.get("input_source", "bluetooth_remote")
        self.priority = int(self.declare_parameter("priority", 30).value)
        self.event_timeout = float(
            self.declare_parameter("event_timeout", 0.0).value
        )
        hold_time = float(
            self.declare_parameter(
                "action_hold_time", self.profile.get("hold_seconds", 5.0)
            ).value
        )
        confirmation_timeout = float(
            self.declare_parameter("confirmation_timeout", 15.0).value
        )
        forward_speed = self._speed_parameter("forward_speed", 0.2)
        lateral_speed = self._speed_parameter("lateral_speed", 0.2)
        angular_speed = self._speed_parameter("angular_speed", 0.4)
        forward_rate = self._speed_parameter("forward_acceleration", 0.5)
        lateral_rate = self._speed_parameter("lateral_acceleration", 0.5)
        angular_rate = self._speed_parameter("angular_acceleration", 1.0)

        self.buttons = ButtonState(
            forward_speed,
            lateral_speed,
            angular_speed,
            self.profile["keys"],
            self.profile.get("axes", {}),
        )
        gesture_class = (
            PressHoldActionState
            if self.profile.get("action_mode") == "short_long"
            else LongPressActionState
        )
        self.actions = gesture_class(
            hold_time,
            confirmation_timeout,
            action_keys=self.profile["action_keys"],
            key_labels=self.profile["action_key_labels"],
        )
        self.key_names = {
            code: role for role, code in self.profile["keys"].items()
        }
        self.key_names.update(
            zip(self.profile["action_keys"], self.profile["action_key_labels"])
        )
        self.preset_motions = {
            int(code): motion
            for code, motion in self.profile.get("preset_motions", {}).items()
        }
        self.key_names.update(
            {
                int(code): label
                for code, label in self.profile.get("preset_key_labels", {}).items()
            }
        )
        self.supported_codes = set(self.key_names)
        self.current_action = ""
        self.ramp = VelocityRamp(forward_rate, lateral_rate, angular_rate)
        self.fds = {}
        self.buffers = {}
        self.disabled_sources = []
        self.stop_event = threading.Event()
        self.timer = None
        self.last_publish_time = time.monotonic()
        self.input_source_registered = False
        self.ownership_verified = False
        self.motion_started_time = None
        self.publisher = None
        self.set_client = None
        self.get_client = None
        self.get_action_client = None
        self.set_action_client = None
        self.tts_client = None
        self.preset_client = None

        if self.execute:
            self.publisher = self.create_publisher(
                McLocomotionVelocity, "/aima/mc/locomotion/velocity", 10
            )
            self.set_client = self.create_client(
                SetMcInputSource, "/aimdk_5Fmsgs/srv/SetMcInputSource"
            )
            self.get_client = self.create_client(
                GetCurrentInputSource, "/aimdk_5Fmsgs/srv/GetCurrentInputSource"
            )
            self.get_action_client = self.create_client(
                GetMcAction, "/aimdk_5Fmsgs/srv/GetMcAction"
            )
            self.set_action_client = self.create_client(
                SetMcAction, "/aimdk_5Fmsgs/srv/SetMcAction"
            )
            self.tts_client = self.create_client(
                PlayTts, "/aimdk_5Fmsgs/srv/PlayTts"
            )
            self.preset_client = self.create_client(
                SetMcPresetMotion, "/aimdk_5Fmsgs/srv/SetMcPresetMotion"
            )

    def _speed_parameter(self, name, default):
        value = abs(float(self.declare_parameter(name, default).value))
        if value > default:
            self.get_logger().warning(
                f"{name}={value} 超过初版上限，已限制为 {default}"
            )
            return default
        return value

    def _set_request(self, action, source_name=None):
        request = SetMcInputSource.Request()
        request.request = CommonRequest()
        request.request.header.stamp = self.get_clock().now().to_msg()
        request.action.value = action
        request.input_source.name = source_name or self.input_source
        request.input_source.priority = self.priority
        request.input_source.timeout = 1000
        return request

    def _call_service(self, client, request, name):
        future = client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=3.0)
        if not future.done():
            future.cancel()
            self.get_logger().error(f"{name} 调用超时")
            return None
        try:
            return future.result()
        except Exception as error:
            self.get_logger().error(f"{name} 调用失败：{error}")
            return None

    def _stop_motion(self):
        self.buttons.clear()
        self.ramp.clear()
        self.motion_started_time = None

    def _get_current_action(self):
        if not self.get_action_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("GetMcAction 服务不可用")
            return None
        request = GetMcAction.Request()
        request.request = CommonRequest()
        request.request.header.stamp = self.get_clock().now().to_msg()
        response = self._call_service(self.get_action_client, request, "GetMcAction")
        if response is None or response.header.code != 0:
            self.get_logger().error("无法读取当前 Action")
            return None
        action = response.info.action_desc
        if not action:
            self.get_logger().error("GetMcAction 返回空 Action")
            return None
        self.current_action = action
        return action

    def _speak(self, text):
        self.get_logger().info(f"语音提示：{text}")
        if not self.execute:
            return False
        if not self.tts_client.wait_for_service(timeout_sec=2.0):
            self.get_logger().warning("PlayTts 服务不可用，仅保留日志提示")
            return False
        request = PlayTts.Request()
        request.header = CommonRequest()
        request.header.header.stamp = self.get_clock().now().to_msg()
        request.tts_req.text = text
        request.tts_req.priority_level.value = TtsPriorityLevel.INTERACTION_L6
        request.tts_req.priority_weight = 0
        request.tts_req.domain = "bluetooth_walk_control"
        request.tts_req.trace_id = f"remote_{time.monotonic_ns()}"
        request.tts_req.is_interrupted = True
        response = self._call_service(self.tts_client, request, "PlayTts")
        if (
            response is None
            or response.header.header.code != 0
            or not response.tts_resp.is_success
        ):
            error = response.tts_resp.error_message if response else "无响应"
            self.get_logger().warning(f"语音播报失败：{error}")
            return False
        return True

    def _request_action(self, action):
        if not self.set_action_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("SetMcAction 服务不可用")
            return False
        request = SetMcAction.Request()
        request.header = RequestHeader()
        request.header.stamp = self.get_clock().now().to_msg()
        request.source = "bluetooth_walk_control"
        request.command = McActionCommand()
        request.command.action_desc = action
        response = self._call_service(
            self.set_action_client, request, f"SetMcAction({action})"
        )
        return (
            response is not None
            and response.response.header.code == 0
            and response.response.state.value == CommonState.SUCCESS
        )

    def _wait_for_action(self, expected_action):
        deadline = time.monotonic() + 30.0
        while (
            rclpy.ok()
            and not self.stop_event.is_set()
            and time.monotonic() < deadline
        ):
            if self._get_current_action() == expected_action:
                return True
            time.sleep(0.5)
        return False

    def _execute_confirmed_action(self, action):
        self._stop_motion()
        expected = (
            "BIPED_WALK_RUN" if action == "STAND_UP" else "PASSIVE_DEFAULT"
        )
        name = "站起" if action == "STAND_UP" else "趴下"
        self._speak(f"正在执行{name}")
        success = self._request_action(action) and self._wait_for_action(expected)
        self.ownership_verified = False
        self.motion_started_time = None
        if success:
            self.current_action = expected
            self._speak(f"{name}完成")
        else:
            self.get_logger().error(f"{name} Action 执行失败")
            self._speak(f"{name}执行失败")
        return success

    def _execute_preset_motion(self, key_code, motion):
        self._stop_motion()
        if self._get_current_action() is None:
            return False
        if self.current_action != "BIPED_WHOLE_BODY_CTRL":
            switcher = McActionSwitcher(self)
            options = McActionSwitchOptions(
                source="bluetooth_walk_control",
                total_timeout=30.0,
            )
            result = switcher.switch_to("BIPED_WHOLE_BODY_CTRL", options)
            if not result.success:
                self.get_logger().error(f"无法进入全身控制模式：{result.message}")
                return False
            self.current_action = "BIPED_WHOLE_BODY_CTRL"

        request = SetMcPresetMotion.Request()
        request.header = RequestHeader()
        request.header.stamp = self.get_clock().now().to_msg()
        request.source = "bluetooth_walk_control"
        request.motion.value = motion
        request.interrupt = False
        request.ani_path = ""
        response = self._call_service(
            self.preset_client, request, f"SetMcPresetMotion({motion})"
        )
        if response is None or response.response.header.code != 0:
            code = response.response.header.code if response else "无响应"
            self.get_logger().error(f"预制动作 {motion} 调用失败：{code}")
            return False
        self.get_logger().info(
            f"{self.key_names.get(key_code, key_code)} 已触发动作 {motion}"
        )
        return True

    def _delete_input_source(self):
        response = self._call_service(
            self.set_client, self._set_request(1003), "SetMcInputSource(DELETE)"
        )
        success = response is not None and response.response.header.code == 0
        if not success:
            code = response.response.header.code if response else "无响应"
            self.get_logger().warning(f"删除输入源 {self.input_source} 未成功：{code}")
        return success

    def _register_input_source(self):
        if not self.set_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("SetMcInputSource 服务不可用")
            return False
        self._delete_input_source()
        response = self._call_service(
            self.set_client, self._set_request(1001), "SetMcInputSource(ADD)"
        )
        if response is None or response.response.header.code != 0:
            code = response.response.header.code if response else "无响应"
            self.get_logger().error(f"注册输入源失败：{code}")
            return False
        self.input_source_registered = True
        self.get_logger().info(
            f"输入源已注册：{self.input_source}，priority={self.priority}"
        )
        return True

    def _disable_conflicting_sources(self):
        for source in self.profile["disable_sources"]:
            response = self._call_service(
                self.set_client,
                self._set_request(2002, source),
                f"SetMcInputSource(DISABLE {source})",
            )
            if response is None or response.response.header.code != 0:
                code = response.response.header.code if response else "无响应"
                self.get_logger().error(f"禁用冲突输入源 {source} 失败：{code}")
                return False
            self.disabled_sources.append(source)
            self.get_logger().info(f"已禁用冲突输入源：{source}")
        return True

    def _restore_conflicting_sources(self):
        if self.current_action in STANDING_ACTIONS and self.disabled_sources:
            self.get_logger().warning(
                "机器人仍处于站立/走跑状态，为避免冲突输入源接管，退出后保持其禁用状态"
            )
            self.disabled_sources = []
            return
        for source in self.disabled_sources:
            response = self._call_service(
                self.set_client,
                self._set_request(2001, source),
                f"SetMcInputSource(ENABLE {source})",
            )
            if response is None or response.response.header.code != 0:
                self.get_logger().warning(f"恢复输入源 {source} 失败")
            else:
                self.get_logger().info(f"已恢复输入源：{source}")
        self.disabled_sources = []

    def _verify_control_ownership(self, allow_empty=False):
        if not self.get_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error("GetCurrentInputSource 服务不可用")
            return False
        request = GetCurrentInputSource.Request()
        request.request = CommonRequest()
        request.request.header.stamp = self.get_clock().now().to_msg()
        response = self._call_service(
            self.get_client, request, "GetCurrentInputSource"
        )
        if response is None or response.response.header.code != 0:
            self.get_logger().error("无法确认当前运控输入源")
            return False
        current = response.input_source.name
        if not current and allow_empty:
            self.get_logger().warning(
                "当前输入源为空，属于初始化未受控状态；将在首次运动指令后复核"
            )
            return True
        if current != self.input_source:
            self.get_logger().error(
                f"当前输入源为 {current or '(empty)'}，不是 {self.input_source}，拒绝运动"
            )
            return False
        self.ownership_verified = True
        self.get_logger().info(f"已确认运控控制权：{current}")
        return True

    def _prepare_motion(self):
        current_action = self._get_current_action()
        if current_action is None:
            return False
        if current_action in GROUND_ACTIONS:
            labels = " + ".join(self.profile["action_key_labels"])
            self.get_logger().info(
                f"当前 Action 为 {current_action}，保持趴下并等待 {labels} 动作序列发起站起确认"
            )
        else:
            switcher = McActionSwitcher(self)
            options = McActionSwitchOptions(
                source="bluetooth_walk_control",
                total_timeout=30.0,
            )
            result = switcher.switch_to("BIPED_WALK_RUN", options)
            if not result.success:
                self.get_logger().error(f"无法进入 BIPED_WALK_RUN：{result.message}")
                return False
            self.current_action = "BIPED_WALK_RUN"
        if not self._register_input_source():
            return False
        if not self._disable_conflicting_sources():
            return False
        self._stop_motion()
        for _ in range(3):
            self._publish_velocity()
            rclpy.spin_once(self, timeout_sec=0.02)
            time.sleep(0.03)
        return self._verify_control_ownership(allow_empty=True)

    def _publish_velocity(self):
        now = time.monotonic()
        elapsed = min(max(now - self.last_publish_time, 0.0), 0.1)
        self.last_publish_time = now
        command = self.ramp.advance(self.buttons.target(), elapsed)
        msg = McLocomotionVelocity()
        msg.header = MessageHeader()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.source = self.input_source
        msg.forward_velocity = command.forward
        msg.lateral_velocity = command.lateral
        msg.angular_velocity = command.angular
        msg.pitch_velocity = 0.0
        msg.level = 0.0
        self.publisher.publish(msg)

    def _process_events(self):
        readable, _, _ = select.select(list(self.fds), [], [], 0)
        for fd in readable:
            chunk = os.read(fd, 4096)
            if not chunk:
                raise OSError(f"遥控器输入设备已断开：{self.fds[fd]}")
            self.buffers[fd] += chunk
            while len(self.buffers[fd]) >= EVENT_STRUCT.size:
                raw = self.buffers[fd][: EVENT_STRUCT.size]
                self.buffers[fd] = self.buffers[fd][EVENT_STRUCT.size :]
                _, _, event_type, code, value = EVENT_STRUCT.unpack(raw)
                if event_type == EV_ABS:
                    if self.execute and self.current_action not in STANDING_ACTIONS:
                        continue
                    target = self.buttons.handle_axis(code, value)
                    if target is None:
                        continue
                    if (
                        self.execute
                        and not self.ownership_verified
                        and self.motion_started_time is None
                        and target != VelocityCommand()
                    ):
                        self.motion_started_time = time.monotonic()
                    self.get_logger().info(
                        f"ABS_{code}={value}; target: "
                        f"forward={target.forward:.2f} m/s, "
                        f"lateral={target.lateral:.2f} m/s, "
                        f"angular={target.angular:.2f} rad/s"
                    )
                    continue
                if event_type != EV_KEY or code not in self.supported_codes:
                    continue
                was_combo_active = self.actions.combo_active
                confirmed_action = self.actions.handle_event(code, value)
                if confirmed_action:
                    if self.execute:
                        self._execute_confirmed_action(confirmed_action)
                    else:
                        self.get_logger().info(f"无运动模式收到 Action 确认：{confirmed_action}")
                    continue
                if self.actions.combo_active:
                    if not was_combo_active:
                        self._stop_motion()
                        labels = " + ".join(self.profile["action_key_labels"])
                        self.get_logger().info(f"检测到 {labels} 动作序列，已抑制平移")
                    continue
                if self.actions.pending:
                    continue
                if self.execute and self.current_action not in STANDING_ACTIONS:
                    continue
                if value == 1 and code in self.preset_motions:
                    motion = self.preset_motions[code]
                    if self.execute:
                        self._execute_preset_motion(code, motion)
                    else:
                        self.get_logger().info(
                            f"{self.key_names[code]} 对应预制动作 {motion}，无运动模式不执行"
                        )
                    continue
                target = self.buttons.handle_event(code, value)
                if target is None:
                    continue
                if (
                    self.execute
                    and not self.ownership_verified
                    and self.motion_started_time is None
                    and target != VelocityCommand()
                ):
                    self.motion_started_time = time.monotonic()
                action = "pressed" if value else "released"
                self.get_logger().info(
                    f"{self.key_names[code]} {action}; target: "
                    f"forward={target.forward:.2f} m/s, "
                    f"lateral={target.lateral:.2f} m/s, "
                    f"angular={target.angular:.2f} rad/s"
                )

    def _stop_and_release(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        self.buttons.clear()
        self.actions.reset()
        self.ramp.clear()

        if self.execute and self.input_source_registered:
            for _ in range(3):
                self._publish_velocity()
                rclpy.spin_once(self, timeout_sec=0.02)
                time.sleep(0.03)
            self._delete_input_source()
            self.input_source_registered = False

        if self.execute:
            self._restore_conflicting_sources()
            self.get_logger().info(
                "已停车并释放输入源；未自动切换 Action，运控可能仍处于 BIPED_WALK_RUN"
            )

    def run(self):
        try:
            devices = find_profile_inputs(self.profile, self.requested_device)
            for device in devices:
                fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
                self.fds[fd] = device
                self.buffers[fd] = b""
            self.get_logger().info(
                f"当前遥控器：{self.profile['name']}（{self.profile['address']}），"
                f"输入节点：{', '.join(devices)}"
            )
            if self.execute:
                self.get_logger().warning("实机运动模式已开启，请确认周围安全并准备独立急停")
                if not self._prepare_motion():
                    return 1
                self.last_publish_time = time.monotonic()
                self.timer = self.create_timer(0.02, self._publish_velocity)
            else:
                self.get_logger().info("无运动验证模式：不调用运控服务，不发布速度")

            self.get_logger().info(
                f"运动键位：{self.profile['keys']}；"
                f"动作组合键：{self.profile['action_key_labels']}；"
                "松开停车，Ctrl+C 退出"
            )
            while rclpy.ok() and not self.stop_event.is_set():
                self._process_events()
                prompt = self.actions.check_prompt(self.current_action)
                if prompt:
                    self._stop_motion()
                    self._speak(prompt.text)
                if self.actions.expire_confirmation():
                    self._stop_motion()
                    self._speak("确认已超时，动作取消")
                if self.event_timeout > 0.0 and self.buttons.expire_if_stale(
                    self.event_timeout
                ):
                    self.ramp.clear()
                    self.get_logger().warning("输入事件超时，已清空全部运动指令")
                if (
                    self.execute
                    and not self.ownership_verified
                    and self.motion_started_time is not None
                    and time.monotonic() - self.motion_started_time >= 1.0
                ):
                    if not self._verify_control_ownership():
                        self.buttons.clear()
                        self.ramp.clear()
                        raise RuntimeError("首次运动后控制权复核失败，已停车")
                rclpy.spin_once(self, timeout_sec=0.02)
            return 0
        except (OSError, RuntimeError) as error:
            self.get_logger().error(str(error))
            return 1
        finally:
            for fd in self.fds:
                os.close(fd)
            self.fds = {}
            self.buffers = {}
            self._stop_and_release()


def main(args=None):
    rclpy.init(args=args)
    node = WalkControl()

    def request_stop(signum, frame):
        node.stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        return node.run()
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
