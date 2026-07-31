#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${ROS_DISTRO:-}" ]]; then
  echo "ROS_DISTRO is not set. Source ROS 2 first:" >&2
  echo "  source /opt/ros/jazzy/setup.bash" >&2
  exit 2
fi

python -m pip install -e "${ROOT}/packages/nodrix-mapping"
python -m pip install -e "${ROOT}/packages/nodrix-ros2"

nodrix provider list
nodrix doctor --provider nodrix.ros2
