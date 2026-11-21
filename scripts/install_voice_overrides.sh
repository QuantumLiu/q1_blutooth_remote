#!/usr/bin/env bash
set -eo pipefail

AGENT_CFG="${Q1_AGENT_CFG:-/robot/software/aimrt_agent/bin/cfg/q1}"
BACKUP_DIR="${Q1_BACKUP_DIR:-/robot/persist/config}"
export AGENT_CFG BACKUP_DIR

if [[ ! -f "${AGENT_CFG}/nlu_rules.json" ]]; then
  printf '找不到语音配置目录：%s\n' "${AGENT_CFG}" >&2
  exit 1
fi

python3 - <<'PY'
from datetime import datetime
import json
import os
from pathlib import Path

cfg = Path(os.environ["AGENT_CFG"])
backup_dir = Path(os.environ["BACKUP_DIR"])
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")


def load(name):
    path = cfg / name
    data = json.loads(path.read_text(encoding="utf-8"))
    (backup_dir / f"{name}.{stamp}.bak").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return path, data


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# 1. 本地规则优先：本地能识别的指令不再交给云端技能执行。
arb_path, arb = load("nlu_arbitration_config.json")
arb["mode"] = "offline_priority"
save(arb_path, arb)
print(f"已设置本地优先仲裁：{arb_path}")

# 2. 把遥控器指令加入本地规则，命中后执行安全的停车动作，云端不会再执行绑定。
rules_path, rules = load("nlu_rules.json")
keywords = [
    "启动R1遥控",
    "启动R1遥控器",
    "启动r1遥控",
    "启动r1遥控器",
    "启动遥控",
    "启动遥控器",
    "启动语音遥控",
    "启动二十一遥控",
    "启动二一遥控",
    "启动手柄",
    "启动游戏手柄",
    "打开遥控",
    "打开遥控器",
    "打开手柄",
    "开启遥控",
    "绑定蓝牙遥控器",
    "绑定遥控器",
    "绑定蓝牙手柄",
    "绑定手柄",
    "配对遥控器",
    "配对遥控",
]
intent = next(
    (item for item in rules.get("intents", []) if item.get("name") == "r1_remote_control"),
    None,
)
if intent is None:
    rules.setdefault("intents", []).append(
        {
            "name": "r1_remote_control",
            "keywords": keywords,
            "type": "status",
            "action": "freeze",
        }
    )
    save(rules_path, rules)
    print(f"已加入本地遥控指令：{rules_path}")
else:
    merged = list(dict.fromkeys(intent.get("keywords", []) + keywords))
    if merged != intent.get("keywords"):
        intent["keywords"] = merged
        save(rules_path, rules)
        print(f"已更新本地遥控指令关键词：{rules_path}")
    else:
        print("本地遥控指令已存在，跳过")

# 3. 兜底：即使云端仍然命中 bind_device，也不再播报验证码。
skills_path, skills = load("skills.json")
changed = False
for skill in skills.get("skills", []):
    if skill.get("skill_name") == "bind_service_req" and skill.get("execution_sequence"):
        skill["execution_sequence"] = []
        changed = True
if changed:
    save(skills_path, skills)
    print(f"已禁用云端绑定验证码播报：{skills_path}")
else:
    print("云端绑定播报已是空操作，跳过")
PY

printf '\n配置已更新。重启机器人后生效：\n'
printf '  sudo reboot\n'
printf '不要单独重启 agent，实测会导致唤醒和 ASR 不工作。\n'
