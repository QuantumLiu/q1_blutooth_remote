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
source "${WORKSPACE_ROOT}/install/setup.bash"
exec ros2 run q1_cpp_template bms_monitor
