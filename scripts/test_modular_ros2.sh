#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export LIVOX_WS="${LIVOX_WS:-/opt/ros/jazzy}"
export ROBOT_WS="${ROBOT_WS:-${ROOT}}"

python -m pytest -q \
  "${ROOT}/packages/nodrix-spatial/tests" \
  "${ROOT}/packages/nodrix-mapping/tests" \
  "${ROOT}/packages/nodrix-ros2/tests"

nodrix validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/input.yaml"

nodrix validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/generic-topic-smoke.yaml"

nodrix validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/orchestrated-ros2.yaml"
