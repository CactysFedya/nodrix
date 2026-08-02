#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export LIVOX_WS="${LIVOX_WS:-/opt/ros/jazzy}"
export ROBOT_WS="${ROBOT_WS:-${ROOT}}"

python -m pytest -q \
  "${ROOT}/tests/test_v210.py" \
  "${ROOT}/tests/test_v220_provider_discovery.py" \
  "${ROOT}/tests/test_v220_sessions.py" \
  "${ROOT}/packages/nodrix-spatial/tests" \
  "${ROOT}/packages/nodrix-mapping/tests" \
  "${ROOT}/packages/nodrix-ros2/tests" \
  "${ROOT}/packages/nodrix-spatial-ros2/tests"

nodrix validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/input.yaml"

nodrix validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/generic-topic-smoke.yaml"

nodrix validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/orchestrated-ros2.yaml"

TEMPLATE_ROOT="$(mktemp -d)"
nodrix init "${TEMPLATE_ROOT}/ros2-project" --template ros2
nodrix validate "${TEMPLATE_ROOT}/ros2-project/pipeline.yaml"
