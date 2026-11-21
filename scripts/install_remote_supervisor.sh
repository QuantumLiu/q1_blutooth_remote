#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_ROOT="${R1_DEPLOY_ROOT:-/robot/software/r1_remote}"

# 找到 process_manager 实际加载的机器人配置，而不是写死型号文件。
PROCESS_CONFIG="${Q1_PROCESS_CONFIG:-}"
if [[ -z "${PROCESS_CONFIG}" ]]; then
  PM_PID="$(pgrep -f 'process_manager --cfg_file_path' | head -n1 || true)"
  if [[ -n "${PM_PID}" && -r "/proc/${PM_PID}/environ" ]]; then
    RUN_ROBOT_FILE="$(tr '\0' '\n' < "/proc/${PM_PID}/environ" | sed -n 's/^RUN_ROBOT_FILE=//p' | head -n1)"
    if [[ -n "${RUN_ROBOT_FILE}" ]]; then
      PROCESS_CONFIG="/robot/software/process_manager/bin/${RUN_ROBOT_FILE#./}"
    fi
  fi
fi

if [[ ! -f "${WORKSPACE_ROOT}/config/remotes.json" ]]; then
  printf '缺少本地遥控器配置，请先执行：\n  cp %s/config/remotes.example.json %s/config/remotes.json\n  chmod 600 %s/config/remotes.json\n' \
    "${WORKSPACE_ROOT}" "${WORKSPACE_ROOT}" "${WORKSPACE_ROOT}" >&2
  exit 1
fi

if [[ -z "${PROCESS_CONFIG}" || ! -f "${PROCESS_CONFIG}" ]]; then
  printf '找不到 process_manager 的机器人配置。\n' >&2
  printf '请用 sudo 运行本脚本，或显式指定：\n  sudo Q1_PROCESS_CONFIG=/path/to/qyXXXX_socX_config.yaml %s\n' "$0" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${WORKSPACE_ROOT}/scripts/env.sh"
"${WORKSPACE_ROOT}/scripts/build.sh"

if [[ -n "${SUDO_USER:-}" ]]; then
  chown -R "${SUDO_USER}:" "${WORKSPACE_ROOT}/build" "${WORKSPACE_ROOT}/install" \
    "${WORKSPACE_ROOT}/log" 2>/dev/null || true
fi

if [[ "${WORKSPACE_ROOT}" != "${DEPLOY_ROOT}" ]]; then
  mkdir -p "${DEPLOY_ROOT}"
  cp -a "${WORKSPACE_ROOT}/src" "${WORKSPACE_ROOT}/scripts" \
    "${WORKSPACE_ROOT}/config" "${WORKSPACE_ROOT}/README.md" \
    "${WORKSPACE_ROOT}/LICENSE" "${WORKSPACE_ROOT}/NOTICE" \
    "${WORKSPACE_ROOT}/docs" "${DEPLOY_ROOT}/"
  Q1_SDK_ROOT="${Q1_SDK_ROOT}" "${DEPLOY_ROOT}/scripts/build.sh"
fi

export PROCESS_CONFIG
export DEPLOY_ROOT
export Q1_SDK_ROOT
python3 - <<'PY'
from datetime import datetime
import os
from pathlib import Path
import re

config = Path(os.environ["PROCESS_CONFIG"])
deploy_root = os.environ["DEPLOY_ROOT"]
sdk_root = os.environ["Q1_SDK_ROOT"]
text = config.read_text(encoding="utf-8")
if '"r1_remote"' in text:
    print("process_manager 已包含 r1_remote，无需重复添加")
    raise SystemExit(0)

stage_section_end = None
for marker in ("\n  cgroup:", "\n  apps:"):
    index = text.find(marker)
    if index != -1 and (stage_section_end is None or index < stage_section_end):
        stage_section_end = index
if stage_section_end is None:
    raise RuntimeError("未找到 process_manager 的 startup_stages/apps 段，未修改配置")
stage_section = text[:stage_section_end]
rc_match = re.search(r'^(\s*)"rc",\s*$', stage_section, re.MULTILINE)
if rc_match:
    indent = rc_match.group(1)
    insert_at = rc_match.end()
    text = text[:insert_at] + "\n" + indent + '"r1_remote",' + text[insert_at:]
else:
    stage_block = '''
    - apps: [
        "r1_remote",
      ]
      delay_after_ms: 1000
'''
    text = text[:stage_section_end] + stage_block + text[stage_section_end:]

app_entry = f'''
    "r1_remote":
      path: "{deploy_root}/scripts/start_remote_supervisor.sh"
      sudo: false
      stderr: "/tmp/r1_remote.err"
      env:
        LOG_PATH: /robot/persist/log/r1_remote
        Q1_SDK_ROOT: {sdk_root}
'''
text = text.rstrip() + "\n" + app_entry

try:
    import yaml
except ImportError:
    yaml = None
if yaml is not None:
    data = yaml.safe_load(text)["process_manager"]
    assert "r1_remote" in data["apps"], "r1_remote 未进入 apps"
    assert any("r1_remote" in stage.get("apps", []) for stage in data["startup_stages"]), \
        "r1_remote 未进入 startup_stages"

backup_dir = Path("/robot/persist/config")
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / f"{config.name}.{datetime.now():%Y%m%d_%H%M%S}.bak"
backup.write_text(config.read_text(encoding="utf-8"), encoding="utf-8")

config.write_text(text, encoding="utf-8")

print(f"配置文件：{config}")
print(f"已备份原配置：{backup}")
print("已添加 r1_remote 语音监督服务，下次机器人启动后生效")
PY
