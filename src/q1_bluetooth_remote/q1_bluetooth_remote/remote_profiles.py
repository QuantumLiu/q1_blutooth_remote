import argparse
import json
import os
from pathlib import Path
import sys

SUPPORTED_ROLES = (
    "forward",
    "backward",
    "turn_left",
    "turn_right",
    "lateral_right",
    "lateral_left",
)


def default_config_path():
    if os.environ.get("Q1_REMOTE_CONFIG"):
        return Path(os.environ["Q1_REMOTE_CONFIG"])
    workspace_config = Path.cwd() / "config" / "remotes.json"
    if workspace_config.exists():
        return workspace_config
    return Path(__file__).resolve().parent.parent / "config" / "remotes.json"


def normalize_address(address):
    return address.strip().upper()


def load_store(path=None):
    path = Path(path) if path else default_config_path()
    with path.open(encoding="utf-8") as stream:
        store = json.load(stream)
    if not isinstance(store.get("profiles"), dict):
        raise ValueError("遥控器档案缺少 profiles 对象")
    return store


def save_store(store, path=None):
    path = Path(path) if path else default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(store, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.replace(path)


def get_profile(store, address=None):
    address = normalize_address(address or store.get("active_address", ""))
    profiles = store["profiles"]
    if address not in profiles:
        raise ValueError(f"未找到遥控器档案：{address or '(未设置默认地址)'}")
    profile = dict(profiles[address])
    profile["address"] = address
    profile.setdefault("keys", {})
    profile.setdefault("inputs", [])
    profile.setdefault("action_keys", [])
    profile.setdefault("action_key_labels", [])
    profile.setdefault("disable_sources", [])
    return profile


def main(args=None):
    parser = argparse.ArgumentParser(description="管理 Q1 蓝牙遥控器地址与按键档案")
    parser.add_argument("--config", help="遥控器 JSON 档案路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="列出所有遥控器")

    show_parser = subparsers.add_parser("show", help="显示指定遥控器档案")
    show_parser.add_argument("address", nargs="?", help="蓝牙地址，默认显示当前档案")

    use_parser = subparsers.add_parser("use", help="设置默认遥控器地址")
    use_parser.add_argument("address")

    key_parser = subparsers.add_parser("set-key", help="修改运动功能键码")
    key_parser.add_argument("address")
    key_parser.add_argument("role", choices=SUPPORTED_ROLES)
    key_parser.add_argument("code", help="Linux 十进制键码，或 none 取消映射")

    options = parser.parse_args(args)
    path = options.config or default_config_path()
    store = load_store(path)

    if options.command == "list":
        for address in sorted(store["profiles"]):
            profile = get_profile(store, address)
            active = "*" if address == store.get("active_address", "") else " "
            print(f"{active} {address}  {profile['name']}")
        return 0

    if options.command == "show":
        profile = get_profile(store, options.address)
        print(json.dumps(profile, ensure_ascii=False, indent=2))
        return 0

    if options.command == "use":
        address = normalize_address(options.address)
        get_profile(store, address)
        store["active_address"] = address
        save_store(store, path)
        print(f"默认遥控器已切换为 {address}")
        return 0

    if options.command == "set-key":
        profile = get_profile(store, options.address)
        if options.code.lower() == "none":
            profile["keys"].pop(options.role, None)
        else:
            code = int(options.code, 0)
            if not 0 <= code <= 0xFFFF:
                raise ValueError("键码必须在 0 到 65535 之间")
            profile["keys"][options.role] = code
        store["profiles"][profile["address"]] = profile
        save_store(store, path)
        print(f"{profile['name']} 的 {options.role} 已更新为 {options.code}")
        return 0
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(1)
