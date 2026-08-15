#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "Python 3 was not found. Set PYTHON_BIN to the interpreter to use." >&2
    exit 1
  fi
fi

LOCAL_PYTHONPATH="${ROOT}/src:${ROOT}/packages/nodrix-spatial/src:${ROOT}/packages/nodrix-mapping/src:${ROOT}/packages/nodrix-ros2/src:${ROOT}/packages/nodrix-spatial-ros2/src"
export PYTHONPATH="${LOCAL_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}"

export LIVOX_WS="${LIVOX_WS:-/opt/ros/jazzy}"
export ROBOT_WS="${ROBOT_WS:-${ROOT}}"

TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "${TEST_ROOT}"' EXIT
"${PYTHON_BIN}" -m venv --system-site-packages "${TEST_ROOT}/venv"
TEST_PYTHON="${TEST_ROOT}/venv/bin/python"
"${TEST_PYTHON}" -m pip install \
  --disable-pip-version-check \
  --no-build-isolation \
  --no-deps \
  --quiet \
  -e "${ROOT}/packages/nodrix-spatial" \
  -e "${ROOT}/packages/nodrix-mapping" \
  -e "${ROOT}/packages/nodrix-ros2" \
  -e "${ROOT}/packages/nodrix-spatial-ros2"

"${TEST_PYTHON}" -m pytest -q \
  "${ROOT}/tests/test_v210.py" \
  "${ROOT}/tests/test_v220_provider_discovery.py" \
  "${ROOT}/tests/test_v220_sessions.py" \
  "${ROOT}/packages/nodrix-spatial/tests" \
  "${ROOT}/packages/nodrix-mapping/tests" \
  "${ROOT}/packages/nodrix-ros2/tests" \
  "${ROOT}/packages/nodrix-spatial-ros2/tests"

export NODRIX_PROVIDER_PATH
NODRIX_PROVIDER_PATH="$(
  "${TEST_PYTHON}" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])'
)"

"${TEST_PYTHON}" -m plyctl.cli validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/input.yaml"

"${TEST_PYTHON}" -m plyctl.cli validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/generic-topic-smoke.yaml"

"${TEST_PYTHON}" -m plyctl.cli validate \
  "${ROOT}/integrations/nodrix-fast-livo2/pipelines/orchestrated-ros2.yaml"

"${TEST_PYTHON}" -m plyctl.cli init "${TEST_ROOT}/ros2-project" --template ros2
"${TEST_PYTHON}" -m plyctl.cli validate "${TEST_ROOT}/ros2-project/pipeline.yaml"
