# Nodrix 2.0.0 verification

Release candidate qualification was completed on 2026-07-30 from the local
source archive, without using the GitHub repository as an implementation
source.

## Verified locally

Environment:

- macOS 26.3.1 on Apple Silicon;
- CPython 3.13.5;
- Apple Clang 21.0.0;
- CMake 4.2.0.

Results:

```text
Repository Python suite:       195 passed, 3 skipped
Unpacked-sdist Python suite:   195 passed, 3 skipped
Opt-in native ABI/stress:        2 passed
C++ Release CTest:             2/2 passed
C++ ASan/UBSan CTest:          2/2 passed
Ruff release rules:            passed
Release metadata:              consistent for 2.0.0
twine sdist/wheel checks:      passed
```

The three normal skips are platform or opt-in cases: Linux `memfd`, the legacy
explicit C ABI example, and the one-million-message stress test. The two opt-in
native tests were then enabled explicitly and passed, including one million
messages without retained plugin buffers. macOS LeakSanitizer is unsupported,
so the local sanitizer run used ASan and UBSan with leak detection disabled;
the Linux CI job keeps leak detection enabled.

## Distribution verification

The source distribution was built in PEP 517 isolation. It contains the public
tests and native SDK sources, contains no compiled objects, and excludes
repository-only `.github` state.

The local wheel was built from the unpacked source distribution:

```text
nodrix-2.0.0.tar.gz
nodrix-2.0.0-cp313-cp313-macosx_10_13_universal2.whl
```

`twine check` accepted both files. The macOS wheel contains executable
`nodrix/bin/nodrix-native-runner`; the runner and all five Python extensions
were inspected with `lipo` and contain both `arm64` and `x86_64`.

A clean virtual environment installed the wheel and, with
`NODRIX_ALLOW_RUNTIME_BUILD=0`, imported every native extension, resolved the
runner from `site-packages`, and executed a 10,000-message native graph. The
smoke run completed at approximately 731,000 messages/second with zero
observed or planned copies. This number is a machine-specific smoke result, not
a portable performance claim.

## Release automation

The tag-triggered release workflow now:

1. verifies that the tag equals the package version;
2. reruns lint, the full Python suite, million-message stress, and CTest;
3. builds and validates one canonical source distribution;
4. builds all wheels from that exact source distribution;
5. publishes through PyPI Trusted Publishing only after every build succeeds.

CI declares CPython 3.11-3.14 coverage for Linux x86-64, Linux ARM64, macOS
Apple Silicon, and Windows x86-64. Those remote platform jobs are release
gates, not claims of local execution.

## Hardware scope

The local qualification covers CPU, shared-memory, native C ABI loading,
ownership, synchronization, reconnect, TLS, package verification, and NDRX2
recovery paths. Raspberry Pi, Jetson, CUDA, DMA-BUF, Vulkan, Metal, and
vendor-specific media accelerators were not available locally. Nodrix preserves
matching opaque device-memory handles, but each hardware plugin still requires
qualification on its target device.
