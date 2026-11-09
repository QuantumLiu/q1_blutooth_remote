#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/env.sh"
if [[ ! -f "${WORKSPACE_ROOT}/install/setup.bash" ]]; then
  printf '工作区尚未构建，请先运行 %s/scripts/build.sh。\n' "${WORKSPACE_ROOT}" >&2
  exit 1
fi
# shellcheck source=/dev/null
if [[ ! -f "${WORKSPACE_ROOT}/config/remotes.json" ]]; then
  printf '缺少本地遥控器配置，请先复制 %s/config/remotes.example.json 为 config/remotes.json 并填入真实地址。\n' "${WORKSPACE_ROOT}" >&2
  exit 1
fi
source "${WORKSPACE_ROOT}/install/setup.bash"
export Q1_WORKSPACE_ROOT="${WORKSPACE_ROOT}"
export Q1_REMOTE_CONFIG="${WORKSPACE_ROOT}/config/remotes.json"
_system_aimdk="${Q1_SYSTEM_AIMDK:-/robot/software/interface/aimdk_msgs/local/lib/python3.10/dist-packages}"
export PYTHONPATH="${_system_aimdk}:${Q1_SDK_ROOT}/examples/python${PYTHONPATH:+:${PYTHONPATH}}"
export LD_LIBRARY_PATH="/robot/software/interface/aimdk_msgs/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
unset _system_aimdk
exec ros2 run q1_bluetooth_remote remote_supervisor "$@"
