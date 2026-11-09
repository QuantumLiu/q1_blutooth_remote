from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class InputDevice:
    name: str
    path: str
    uniq: str


def discover_input_devices():
    proc_devices = Path("/proc/bus/input/devices")
    if not proc_devices.exists():
        return []

    devices = []
    name = ""
    uniq = ""
    handlers = ""
    for line in proc_devices.read_text(encoding="utf-8").splitlines() + [""]:
        if not line:
            match = re.search(r"(?:^|[\s=])(event\d+)(?:\s|$)", handlers)
            if name and match:
                devices.append(InputDevice(name, f"/dev/input/{match.group(1)}", uniq))
            name = ""
            uniq = ""
            handlers = ""
        elif line.startswith("N: "):
            match = re.search(r'Name="(.*)"', line)
            name = match.group(1) if match else line[3:]
        elif line.startswith("U: "):
            match = re.search(r"Uniq=(.*)", line)
            uniq = match.group(1).strip() if match else ""
        elif line.startswith("H: "):
            handlers = line[3:]
    return devices


def find_profile_inputs(profile, requested_device=""):
    if requested_device:
        return [requested_device]

    paths = []
    devices = discover_input_devices()
    for input_name in profile["inputs"]:
        matches = [
            device
            for device in devices
            if device.name == input_name
            and device.uniq.lower() == profile["address"].lower()
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"未找到唯一输入节点：{input_name}（{profile['address']}），"
                "请确认遥控器已连接；也可使用 device 参数手动指定"
            )
        paths.append(matches[0].path)
    if not paths:
        raise RuntimeError(f"遥控器 {profile['name']} 没有配置输入节点")
    return paths
