#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SCRIPT_DIR}/env.sh"
cd "${WORKSPACE_ROOT}"
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release

printf '\n构建完成。可运行：\n'
printf '  %s/scripts/run_cpp.sh\n' "${WORKSPACE_ROOT}"
printf '  %s/scripts/run_python.sh\n' "${WORKSPACE_ROOT}"
printf '  %s/scripts/run_key_capture.sh\n' "${WORKSPACE_ROOT}"
printf '  %s/scripts/run_walk_control.sh\n' "${WORKSPACE_ROOT}"
printf '  %s/scripts/remote_profiles.sh\n' "${WORKSPACE_ROOT}"
printf '  %s/scripts/run_remote_supervisor.sh\n' "${WORKSPACE_ROOT}"
