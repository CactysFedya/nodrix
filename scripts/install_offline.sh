#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
EXTRAS=""
PIP_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --extras)
      EXTRAS="${2:?--extras requires a comma-separated value, for example media,viewer}"
      shift 2
      ;;
    --)
      shift
      PIP_ARGS+=("$@")
      break
      ;;
    *)
      PIP_ARGS+=("$1")
      shift
      ;;
  esac
done

"$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import importlib
import sys

required = {
    "setuptools": "build backend",
    "wheel": "wheel build support",
    "typer": "CLI",
    "pydantic": "configuration models",
    "yaml": "YAML parser (PyYAML)",
    "rich": "terminal output",
}
missing = []
for module, purpose in required.items():
    try:
        importlib.import_module(module)
    except Exception as exc:
        missing.append(f"{module}: {purpose} ({exc})")

if missing:
    print("Offline installation cannot continue. Missing local packages:", file=sys.stderr)
    for item in missing:
        print(f"  - {item}", file=sys.stderr)
    print("Copy the required wheels to this machine and install them with:", file=sys.stderr)
    print("  python3 -m pip install --no-index --find-links ./wheelhouse -r offline-requirements.txt", file=sys.stderr)
    raise SystemExit(2)
PY

TARGET="."
if [[ -n "$EXTRAS" ]]; then
  TARGET=".[${EXTRAS}]"
fi

"$PYTHON_BIN" -m pip install \
  "$TARGET" \
  --no-build-isolation \
  --no-deps \
  "${PIP_ARGS[@]}"

"$PYTHON_BIN" -c 'import nodrix; print(f"Nodrix {nodrix.__version__} installed")'
