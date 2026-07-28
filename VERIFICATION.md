# Nodrix 1.2.0 verification

Nodrix 1.2.0 adds reusable single-node YAML Blocks while preserving compact
and canonical manifests, the Nodrix 1.x Python API, Plugin ABI 1.0, wire
protocol, `.ndrx`, `.ndpkg`, and runtime execution behavior.

## Automated tests

```text
Python/unit/integration: 81 passed
C++ Release CTest:       1/1 passed
Release metadata:        consistent for 1.2.0
```

The new suite covers:

- block expansion into canonical nodes;
- temporary `--block name=path.yaml` replacement;
- short parameter overrides such as `detector.conf=value`;
- unknown-block and duplicate-name diagnostics;
- block listing and inspection in text/JSON form;
- source tracking in `config explain`;
- real execution of resolved block graphs;
- lock-file inclusion of used blocks only;
- checksum failure after a referenced block changes;
- rejection of `--locked` together with `--block`;
- block-based vision project generation.

All earlier compact-manifest, profile, telemetry, process isolation, Media Pack,
Viewer, networking, recording, package, lock, and native-runtime tests remain
green.

## Runtime behavior

A block graph was resolved and executed with the standard unified runtime. The
block aliases became ordinary node names, and a lossless profile delivered all
five generated messages to the sink. No extra runtime object or execution
boundary exists for a block.

## Installed wheel

Built artifact:

```text
nodrix-1.2.0-cp313-cp313-linux_x86_64.whl
```

Verified outside the source tree:

- `nodrix --version` reports 1.2.0;
- a generated vision template contains camera/detector/output blocks;
- `nodrix block list --json` discovers the generated blocks;
- `nodrix inspect --resolved` expands the selected detector into a canonical
  node;
- all four native extensions import.

## Offline source installation

Built artifact:

```text
nodrix-1.2.0.tar.gz
```

Installed with:

```bash
pip install nodrix-1.2.0.tar.gz --no-build-isolation --no-deps
```

The source package compiled and loaded all four native extensions without a
network build-isolation environment.

## Platform scope

The local wheel is a CPython 3.13 Linux x86-64 verification artifact. The
GitHub release workflow remains responsible for manylinux x86-64, manylinux
ARM64/Raspberry Pi, and macOS Apple Silicon wheels for Python 3.11-3.14.
