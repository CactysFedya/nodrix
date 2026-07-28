# Nodrix 1.1.0 verification

Nodrix 1.1.0 adds compact authoring, runtime profiles, auto encoder selection and per-node resource telemetry while preserving the Nodrix 1.x Python API, Plugin ABI 1.0, wire protocol, `.ndrx`, `.ndpkg` and lock-file formats.

## Automated tests

```text
Python/unit/integration: 73 passed
C++ Release CTest:       1/1 passed
Release metadata:        consistent for 1.1.0
```

The new suite covers:

- compact manifests and canonical resolution;
- all runtime profile merge rules;
- repeatable `--set` and profile overrides;
- lock/override conflict protection;
- `config show`, `config explain` and `inspect --resolved`;
- exact process telemetry and shared executor telemetry;
- zombie-process RSS preservation;
- `nodrix top` JSON snapshots;
- Publisher metrics used by Nodrix Viewer;
- auto FFmpeg encoder probing and fallback.

## Media integration

The compact `media` template was created, strictly validated and executed with FFmpeg:

```text
Source frames:    90
Encoder messages: 90
Writer messages:  90
Edge drops:       0
Output codec:     H.264
Resolution:       640x360
```

The full recording path explicitly uses blocking queues, while the exported Viewer stream keeps the low-latency profile queue.

## Installed wheel

Built artifact:

```text
nodrix-1.1.0-cp313-cp313-linux_x86_64.whl
```

Verified outside the source tree:

- `nodrix --version` reports 1.1.0;
- all four native extensions import;
- a generated `core` template validates and completes;
- run reports contain profile/system/node resource telemetry.

## Offline source installation

Built artifact:

```text
nodrix-1.1.0.tar.gz
```

Installed with:

```bash
pip install nodrix-1.1.0.tar.gz --no-build-isolation --no-deps
```

The source package compiled and loaded all four native extensions without a network build-isolation environment.

## Encoder probe

The current test host probed available H.264 encoders. NVENC and VAAPI were rejected by real encode probes and `libx264` was selected as the working fallback. The selection result includes every attempted backend and its failure reason.

## Platform scope

The local wheel is a CPython 3.13 Linux x86-64 verification artifact. The GitHub release workflow remains responsible for manylinux x86-64, manylinux ARM64/Raspberry Pi and macOS Apple Silicon wheels for Python 3.11-3.14.
