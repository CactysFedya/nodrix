#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python -m pytest -q \
  "${ROOT}/packages/nodrix-mapping/tests" \
  "${ROOT}/packages/nodrix-ros2/tests"

nodrix validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/input.yaml"

nodrix validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/generic-topic-smoke.yaml"
