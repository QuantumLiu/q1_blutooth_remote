#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  printf '请通过 source 加载此脚本，或直接使用 scripts/build.sh。\n' >&2
  exit 1
fi

_q1_workspace_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_q1_ros_setup="/opt/ros/${ROS_DISTRO:-humble}/setup.bash"

if [[ ! -f "${_q1_ros_setup}" ]]; then
  printf '找不到 ROS 2 环境：%s\n' "${_q1_ros_setup}" >&2
  return 1
fi

if [[ -z "${Q1_SDK_ROOT:-}" ]]; then
  for _q1_candidate in \
    "${_q1_workspace_root}/../primebot-q1-sdk-main" \
    "${_q1_workspace_root}/deps/primebot_sdk"; do
    if [[ -f "${_q1_candidate}/install/setup.bash" ]]; then
      Q1_SDK_ROOT="$(cd "${_q1_candidate}" && pwd)"
      break
    fi
  done
fi

if [[ -z "${Q1_SDK_ROOT:-}" || ! -f "${Q1_SDK_ROOT}/install/setup.bash" ]]; then
  printf '请设置 Q1_SDK_ROOT 为已编译的 Q1 SDK 根目录。\n' >&2
  return 1
fi

export Q1_SDK_ROOT
# shellcheck source=/dev/null
source "${_q1_ros_setup}"
# shellcheck source=/dev/null
source "${Q1_SDK_ROOT}/install/setup.bash"

unset _q1_workspace_root _q1_ros_setup _q1_candidate
