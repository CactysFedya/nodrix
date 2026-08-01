#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python -m pip install -e "${ROOT}/packages/nodrix-spatial" --no-deps
python -m pip install -e "${ROOT}/packages/nodrix-mapping" --no-deps
python -m pip install -e "${ROOT}/packages/nodrix-ros2" --no-deps

nodrix provider list
nodrix provider info nodrix.spatial
nodrix provider info nodrix.mapping
nodrix provider info nodrix.ros2
