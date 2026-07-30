# Nodrix 2.1.0 verification

Release-candidate qualification was completed on 2026-07-30 from the local
source tree. The 2.1.0 changes add Provider API 1, Unified Doctor, and the
in-tree native NCNN provider without changing the 2.x graph, native ABI, or
configuration contracts.

## Verified locally

Environment:

- macOS on Apple Silicon;
- CPython 3.14.6;
- Apple Clang;
- CMake Release build.

Results:

```text
Repository Python suite with stress:  213 passed, 2 skipped
C++ Release CTest:                     3/3 passed
C++ ASan/UBSan CTest:                  3/3 passed
Ruff release rules:                    passed
Release metadata:                      consistent for 2.1.0
twine sdist/wheel checks:              passed
```

The two normal skips are platform-specific cases. The one-million-message
stress test was enabled explicitly with `NODRIX_STRESS=1`. The Python suite
also used the actual locally compiled NCNN provider through
`NODRIX_NCNN_PLUGIN`.

Provider qualification covered:

- metadata-only discovery without importing provider packages;
- lazy import only after policy and compatibility checks;
- duplicate, corrupt, incompatible, and missing-feature rejection;
- Ed25519 signing, tamper rejection, trust-store lookup, and allowlists;
- production rejection of unsigned providers before their code is imported;
- legacy built-in capability descriptors;
- safe and deep Unified Doctor modes;
- the `provider list`, `provider info`, and `provider verify` CLI.

Native NCNN qualification covered:

- a Release build against the pinned NCNN 20260526 source and SHA-256;
- static NCNN linkage into the provider, with only system dynamic libraries;
- C ABI loading, Unicode JSON configuration, validation, and ownership;
- modern Ultralytics, objectness, transposed, and one-dimensional outputs;
- class filtering, confidence filtering, and deterministic NMS;
- Python `Frame` validation and `ManagedBuffer` offset preservation;
- actual SqueezeNet model loading and inference through the Python adapter;
- 100 consecutive in-process inferences and 20 fresh processes with five
  inferences each.

The repeated real-model test exposed a one-dimensional NCNN output
interpretation error that could cause `SIGBUS`. A regression test was added,
the matrix view was corrected, and all repeated-process tests passed after the
fix.

## Distribution verification

The source distribution was built in PEP 517 isolation. It contains Provider
API documentation, the external-provider example, public tests, native SDK
sources, and the NCNN provider source, and contains no compiled objects.

The local wheel was built only from the unpacked canonical source
distribution, with the pinned NCNN source supplied offline:

```text
nodrix-2.1.0.tar.gz
nodrix-2.1.0-cp314-cp314-macosx_26_0_arm64.whl
```

`twine check` accepted both files. Wheel inspection confirmed all five Python
native extensions, the standalone runner, and the statically linked native
NCNN provider. The provider has no non-system dynamic library dependency.

The wheel was then installed with its declared dependencies into a fresh
virtual environment outside the repository. With
`NODRIX_ALLOW_RUNTIME_BUILD=0`, the smoke test:

- imported every native extension;
- located the packaged runner and NCNN provider;
- reported Nodrix 2.1.0 through the installed CLI;
- returned a successful Vision Unified Doctor report;
- loaded the real SqueezeNet `.param`/`.bin` model and completed 100
  consecutive inferences through the provider packaged in the wheel.

The buildable provider under `examples/provider_api` was previously packaged
and installed as an external wheel. Discovery read its metadata without
importing the package; selecting its node then loaded the runtime lazily.

## Remote release gates

The tag-triggered workflow is the authority for the published platform matrix.
It reruns lint, Python tests, stress, CTest, and a real NCNN compile/smoke gate;
builds one canonical source distribution; builds every wheel from it; verifies
that every official wheel contains the native NCNN provider; and publishes
only after all jobs succeed.

CI declares CPython 3.11–3.14 coverage for Linux x86-64, Linux ARM64, macOS
Apple Silicon, and Windows x86-64. These jobs are required release gates and
are not claimed as locally executed. Tagging and publication are intentionally
deferred until the feature branch has passed review and remote CI.

## Hardware scope

The local qualification covers CPU, shared memory, native C ABI loading,
ownership, synchronization, reconnect, TLS, package verification, Provider API
policy, NDRX2 recovery paths, and real NCNN inference on Apple Silicon.
Raspberry Pi, Jetson, CUDA, DMA-BUF, Vulkan, Metal, and vendor-specific media
accelerators were not available locally. The native provider is release-gated
on ARM64, but model-specific latency and thermals still require qualification
on the intended target device.
