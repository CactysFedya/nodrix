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

if ! command -v cmake >/dev/null 2>&1; then
  echo "Offline installation requires CMake to build the packaged native runner." >&2
  exit 2
fi
if ! command -v c++ >/dev/null 2>&1 &&
   ! command -v g++ >/dev/null 2>&1 &&
   ! command -v clang++ >/dev/null 2>&1; then
  echo "Offline installation requires a C++20 compiler." >&2
  exit 2
fi

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
    "packaging": "version and compatibility checks",
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

NODRIX_ALLOW_RUNTIME_BUILD=0 "$PYTHON_BIN" - <<'PY'
from pathlib import Path
import subprocess
import tempfile

import nodrix
import plyctl
import nodrix._native_buffer
import nodrix._native_device
import nodrix._native_plugin
import nodrix._native_queue
import nodrix._native_tracking
from nodrix.native_runtime import NativeToolchain

runner = NativeToolchain(Path(tempfile.gettempdir())).ensure_runner()
version = subprocess.run(
    [str(runner), "--version"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
if version != f"nodrix-native-runner {plyctl.__version__}":
    raise SystemExit(
        f"Packaged native runner version mismatch: {version}"
    )
if plyctl.Message is not nodrix.Message:
    raise SystemExit("Plyctl and Nodrix compatibility imports disagree")
print(f"Plyctl {plyctl.__version__} installed; {version}")
PY
