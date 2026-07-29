# Nodrix 1.0.1 — Packaging and installation stabilization

Nodrix 1.0.1 is a patch release. It does not change the public Python API, plugin ABI, pipeline schema, wire protocol, or runtime behavior.

## Changes

- Removed the failing macOS Intel wheel job from the release matrix; 1.0.1 publishes Linux x86-64, Linux ARM64 and macOS Apple Silicon wheels.
- Updated official GitHub Actions to Node.js 24 based major versions.
- Pinned `cibuildwheel` to 3.4.1 for deterministic release builds.
- Lowered the source-build requirement from `setuptools>=77` to `setuptools>=68`.
- Moved license-file discovery to stable setuptools metadata and removed SPDX-expression parsing from the offline build path, avoiding the `packaging.licenses` failure seen on Raspberry Pi installations.
- Added an offline installation preflight script and Russian offline-installation guide.
- Updated installation, publishing and Raspberry Pi documentation.

## Compatibility

- Python API: unchanged.
- C++ Plugin ABI: unchanged (`1.0`, numeric value `65536`).
- Pipeline manifests: unchanged.
- `.ndrx`, `.ndpkg`, wire schema and lock file: unchanged.
