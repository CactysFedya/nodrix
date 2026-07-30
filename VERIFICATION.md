# Nodrix 2.1.0 verification

Release-candidate qualification was completed on 2026-07-30 from the local
source tree. The 2.1.0 changes add Provider API 1 and Unified Doctor without
changing the 2.x graph, native ABI, or configuration contracts.

## Verified locally

Environment:

- macOS on Apple Silicon;
- CPython 3.14.6;
- Apple Clang;
- CMake Release build.

Results:

```text
Repository Python suite with stress:  206 passed, 2 skipped
Provider API 1 focused suite:           9 passed
2.x compatibility subset:              43 passed
C++ Release CTest:                     2/2 passed
Ruff release rules:                    passed
Release metadata:                      consistent for 2.1.0
twine sdist/wheel checks:              passed
```

The two normal skips are platform-specific cases. The one-million-message
stress test was enabled explicitly with `NODRIX_STRESS=1` and passed.

Provider qualification covered:

- metadata-only discovery without importing provider packages;
- lazy import only after policy and compatibility checks;
- duplicate, corrupt, incompatible, and missing-feature rejection;
- Ed25519 signing, tamper rejection, trust-store lookup, and allowlists;
- production rejection of unsigned providers before their code is imported;
- legacy built-in capability descriptors;
- safe and deep Unified Doctor modes;
- the `provider list`, `provider info`, and `provider verify` CLI.

## Distribution verification

The source distribution was built in PEP 517 isolation. It contains Provider
API documentation, the external-provider example, public tests, and native SDK
sources, and contains no compiled objects.

The local wheel was built from the unpacked canonical source distribution:

```text
nodrix-2.1.0.tar.gz
nodrix-2.1.0-cp314-cp314-macosx_26_0_arm64.whl
```

`twine check` accepted both files. A clean wheel smoke test imports every
native extension with `NODRIX_ALLOW_RUNTIME_BUILD=0`, locates the packaged
runner, verifies runner version 2.1.0, and exercises Provider API and Unified
Doctor commands.

The buildable provider under `examples/provider_api` was also packaged and
installed as an external wheel. Discovery read its metadata without importing
the package; selecting its node then loaded the runtime lazily.

## Remote release gates

The tag-triggered workflow remains the authority for the published platform
matrix. It reruns lint, Python tests, stress, and CTest, builds one canonical
source distribution, builds every wheel from it, and publishes only after all
jobs succeed.

CI declares CPython 3.11–3.14 coverage for Linux x86-64, Linux ARM64, macOS
Apple Silicon, and Windows x86-64. These jobs are required release gates and
are not claimed as locally executed. Tagging and publication are intentionally
deferred until the feature branch has passed review and remote CI.

## Hardware scope

The local qualification covers CPU, shared memory, native C ABI loading,
ownership, synchronization, reconnect, TLS, package verification, Provider API
policy, and NDRX2 recovery paths. Raspberry Pi, Jetson, CUDA, DMA-BUF, Vulkan,
Metal, and vendor-specific media accelerators were not available locally.
Each hardware provider still requires qualification on its target device.
