#!/usr/bin/env python3

import argparse
import os
from pathlib import Path
import re
import select
import struct
import sys

EV_KEY = 0x01
EVENT_STRUCT = struct.Struct("@qqHHi")
VALUE_NAMES = {0: "released", 1: "pressed", 2: "repeated"}
KEY_NAMES = {
    13: "KEY_EQUAL",
    12: "KEY_MINUS",
    42: "KEY_LEFTSHIFT",
    54: "KEY_RIGHTSHIFT",
    78: "KEY_KPPLUS",
    74: "KEY_KPMINUS",
    103: "KEY_UP",
    105: "KEY_LEFT",
    106: "KEY_RIGHT",
    108: "KEY_DOWN",
    113: "KEY_MUTE",
    114: "KEY_VOLUMEDOWN",
    115: "KEY_VOLUMEUP",
    119: "KEY_PAUSE",
    158: "KEY_BACK",
    163: "KEY_NEXTSONG",
    164: "KEY_PLAYPAUSE",
    165: "KEY_PREVIOUSSONG",
    166: "KEY_STOPCD",
    353: "KEY_SELECT",
}


def discover_devices():
    proc_devices = Path("/proc/bus/input/devices")
    if not proc_devices.exists():
        return []

    devices = []
    name = ""
    handlers = ""
    for line in proc_devices.read_text(encoding="utf-8").splitlines() + [""]:
        if not line:
            match = re.search(r"(?:^|\s)(event\d+)(?:\s|$)", handlers)
            if name and match:
                devices.append((name, f"/dev/input/{match.group(1)}"))
            name = ""
            handlers = ""
        elif line.startswith("N: "):
            match = re.search(r'Name="(.*)"', line)
            name = match.group(1) if match else line[3:]
        elif line.startswith("H: "):
            handlers = line[3:]
    return devices


def select_devices(devices, requested_device):
    if requested_device:
        return [(requested_device, requested_device)]
    remote_devices = [
        device
        for device in devices
        if any(word in device[0].lower() for word in ("bluetooth", "remote", "magicsee", "r1"))
    ]
    return remote_devices or devices


def print_devices(devices):
    if not devices:
        print("未发现 Linux 输入设备。")
        return
    for name, path in devices:
        print(f"{path}\t{name}")


def print_key_event(device, event):
    seconds, microseconds, event_type, code, value = event
    if event_type != EV_KEY:
        return
    name, path = device
    key_name = KEY_NAMES.get(code, "UNKNOWN_KEY")
    value_name = VALUE_NAMES.get(value, "unknown")
    print(
        f"{path} [{name}] time={seconds}.{microseconds:06d} "
        f"type=EV_KEY code={code} key={key_name} "
        f"value={value} action={value_name}",
        flush=True,
    )


def capture(devices):
    open_devices = {}
    buffers = {}
    for device in devices:
        try:
            fd = os.open(device[1], os.O_RDONLY | os.O_NONBLOCK)
        except OSError as error:
            print(f"无法打开 {device[1]}：{error}", file=sys.stderr)
            continue
        open_devices[fd] = device
        buffers[fd] = b""

    if not open_devices:
        return 1

    print("监听以下输入设备：")
    print_devices(list(open_devices.values()))
    print("请依次短按 +、-、暂停，观察每个键的按下和松开事件；Ctrl+C 结束。")
    print("当前程序只读取输入，不发送任何运动指令。", flush=True)

    try:
        while open_devices:
            readable, _, _ = select.select(list(open_devices), [], [], 1.0)
            for fd in readable:
                try:
                    chunk = os.read(fd, 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    name, path = open_devices[fd]
                    print(f"{path} [{name}] 输入设备已断开。", file=sys.stderr)
                    os.close(fd)
                    del open_devices[fd]
                    del buffers[fd]
                    continue

                buffers[fd] += chunk
                while len(buffers[fd]) >= EVENT_STRUCT.size:
                    raw = buffers[fd][: EVENT_STRUCT.size]
                    buffers[fd] = buffers[fd][EVENT_STRUCT.size :]
                    print_key_event(open_devices[fd], EVENT_STRUCT.unpack(raw))
    except KeyboardInterrupt:
        print("\n采集结束。")
    finally:
        for fd in open_devices:
            os.close(fd)
    return 0


def main(args=None):
    parser = argparse.ArgumentParser(description="采集蓝牙遥控器的 Linux 原始按键信号")
    parser.add_argument("--device", help="只监听指定的 /dev/input/eventX 节点")
    parser.add_argument("--list", action="store_true", help="列出输入设备后退出")
    options = parser.parse_args(args)

    devices = discover_devices()
    if options.list:
        print_devices(devices)
        return 0

    selected = select_devices(devices, options.device)
    if not selected:
        print("未发现输入设备，请先连接蓝牙遥控器。", file=sys.stderr)
        return 1
    return capture(selected)


if __name__ == "__main__":
    raise SystemExit(main())
