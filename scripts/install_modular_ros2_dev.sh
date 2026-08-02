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

"${PYTHON_BIN}" -m pip install -e "${ROOT}/packages/nodrix-spatial" --no-deps
"${PYTHON_BIN}" -m pip install -e "${ROOT}/packages/nodrix-mapping" --no-deps
"${PYTHON_BIN}" -m pip install -e "${ROOT}/packages/nodrix-ros2" --no-deps
"${PYTHON_BIN}" -m pip install -e "${ROOT}/packages/nodrix-spatial-ros2" --no-deps

"${PYTHON_BIN}" -m nodrix.cli provider list
"${PYTHON_BIN}" -m nodrix.cli provider info nodrix.spatial
"${PYTHON_BIN}" -m nodrix.cli provider info nodrix.mapping
"${PYTHON_BIN}" -m nodrix.cli provider info nodrix.ros2
"${PYTHON_BIN}" -m nodrix.cli provider info nodrix.ros2.spatial
