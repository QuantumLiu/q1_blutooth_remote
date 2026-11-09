#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_PATH="${LOG_PATH:-/robot/persist/log/r1_remote}"
mkdir -p "${LOG_PATH}" 2>/dev/null || true

export Q1_WORKSPACE_ROOT="${WORKSPACE_ROOT}"
export Q1_REMOTE_CONFIG="${WORKSPACE_ROOT}/config/remotes.json"
exec "${WORKSPACE_ROOT}/scripts/run_remote_supervisor.sh" "$@"
