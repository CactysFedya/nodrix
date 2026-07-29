# Nodrix 1.2.1 — Cross-platform stabilization

Nodrix 1.2.1 is a patch release. It does not introduce a new manifest model,
public Node API, wire protocol, record format, package format, or plugin ABI.

## Included fixes

- Python 3.11 and 3.12 no longer receive the Python 3.13-only
  `SharedMemory(track=...)` argument.
- Python 3.13+ shared-memory mappings disable resource tracking because Nodrix
  owns the segment lifetime explicitly.
- POSIX shared-memory names are normalized and shortened for the stricter macOS
  name limit while remaining deterministic.
- macOS resource telemetry obtains installed physical memory through
  `sysctl -n hw.memsize` when `os.sysconf` does not expose it.
- Editable installation is the single native-extension build step; release
  instructions no longer rebuild extensions through `setup.py`.
- The native runner reports the package/CMake project version instead of the
  stale hard-coded `0.6.0` value.

## New regression coverage

- Shared-memory compatibility tests for Python 3.12 and 3.13 behavior.
- Portable shared-memory naming and pool reuse/cleanup tests.
- macOS physical-memory fallback test.
- A native C++ graph end-to-end test that compiles the runner and executes
  `synthetic_source -> identity -> counter_sink`.
- AddressSanitizer and UndefinedBehaviorSanitizer CI for the native core.

## Release gate

Run from a clean checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,all]"
pytest -q

cmake -S src/nodrix/native -B build/native \
  -DCMAKE_BUILD_TYPE=Release \
  -DNODRIX_NATIVE_MARCH_NATIVE=OFF
cmake --build build/native --parallel
ctest --test-dir build/native --output-on-failure

cmake -S src/nodrix/native -B build/native-sanitized \
  -DCMAKE_BUILD_TYPE=Debug \
  -DNODRIX_NATIVE_LTO=OFF \
  -DNODRIX_NATIVE_MARCH_NATIVE=OFF \
  -DNODRIX_NATIVE_SANITIZERS=ON
cmake --build build/native-sanitized --parallel
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
ctest --test-dir build/native-sanitized --output-on-failure

NODRIX_NATIVE_E2E=1 pytest -q tests/test_native_runtime.py -k executes
python scripts/check_release.py --version-only
python -m build
python -m twine check dist/*
```

The release tag may be created only after Linux x86-64, Linux ARM64, macOS
Apple Silicon, Python 3.11-3.14, package build, native E2E, and sanitizer jobs
are green.
