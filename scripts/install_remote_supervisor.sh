#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_ROOT="${R1_DEPLOY_ROOT:-/robot/software/r1_remote}"
PROCESS_CONFIG="${Q1_PROCESS_CONFIG:-/robot/software/process_manager/bin/cfg/q1_v2d0_soc1_config.yaml}"

if [[ ! -f "${WORKSPACE_ROOT}/config/remotes.json" ]]; then
  printf '缺少本地遥控器配置，请先执行：\n  cp %s/config/remotes.example.json %s/config/remotes.json\n  chmod 600 %s/config/remotes.json\n' \
    "${WORKSPACE_ROOT}" "${WORKSPACE_ROOT}" "${WORKSPACE_ROOT}" >&2
  exit 1
fi

if [[ ! -f "${PROCESS_CONFIG}" ]]; then
  printf '找不到 process_manager 配置：%s\n' "${PROCESS_CONFIG}" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${WORKSPACE_ROOT}/scripts/env.sh"
"${WORKSPACE_ROOT}/scripts/build.sh"

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

config = Path(os.environ["PROCESS_CONFIG"])
deploy_root = os.environ["DEPLOY_ROOT"]
sdk_root = os.environ["Q1_SDK_ROOT"]
text = config.read_text(encoding="utf-8")
if '"r1_remote"' in text:
    print("process_manager 已包含 r1_remote，无需重复添加")
    raise SystemExit(0)

startup_marker = '''        "percep"
      ]
      delay_after_ms: 8000'''
startup_replacement = '''        "percep",
        "r1_remote"
      ]
      delay_after_ms: 8000'''
if startup_marker not in text:
    raise RuntimeError("未找到预期的第二阶段 startup_stages，未修改配置")

app_entry = f'''
    "r1_remote":
      path: "{deploy_root}/scripts/start_remote_supervisor.sh"
      sudo: false
      stderr: "/tmp/r1_remote.err"
      env:
        LOG_PATH: /robot/persist/log/r1_remote
        Q1_SDK_ROOT: {sdk_root}
'''
backup_dir = Path("/robot/persist/config")
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / f"{config.name}.{datetime.now():%Y%m%d_%H%M%S}.bak"
backup.write_text(text, encoding="utf-8")
text = text.replace(startup_marker, startup_replacement, 1)
config.write_text(text.rstrip() + "\n" + app_entry, encoding="utf-8")
print(f"已备份原配置：{backup}")
print("已添加 r1_remote 语音监督服务，下次机器人启动后生效")
PY
