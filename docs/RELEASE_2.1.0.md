# Nodrix 2.1.0

Nodrix 2.1.0 introduces Provider API 1 and one unified doctor while preserving
all stable 2.0 contracts: Manifest v2, Python Node API, Plugin C ABI 2,
existing Node ids, `nodrix.lock`, NDRX2, the native runner, pipelines, and CLI
commands.

## Native NCNN provider

The Vision provider now includes `vision.ncnn_detector_native`. Its production
path is:

```text
Plugin C ABI 2
→ NCNN C++ preprocessing and inference
→ C++ YOLO decode/filter/NMS
→ versioned NDT2 detections
→ public Nodrix Detections
```

It does not import the Python NCNN binding and does not need
`execution.isolation: process`. The old `vision.ncnn_detector` remains a
source-compatible Python reference/fallback.

Official wheels build the provider from the pinned NCNN 20260526 full source
and verify SHA-256 before compilation. Source builds are explicit:

```bash
NODRIX_BUILD_NCNN_PLUGIN=1 NODRIX_FETCH_NCNN=1 \
  python -m build --wheel
```

Offline builds use an already verified source tree:

```bash
NODRIX_BUILD_NCNN_PLUGIN=1 \
NODRIX_FETCH_NCNN=0 \
NODRIX_NCNN_SOURCE_DIR=/opt/src/ncnn-20260526 \
  python -m build --wheel
```

The adapter validates exact BGR8 geometry, shape, stride, dtype, channels, and
payload length before crossing the C ABI. Model paths are resolved against the
pipeline project, including Unicode paths. C++ golden tests cover modern,
objectness, transposed, xyxy, class filtering, and NMS layouts.

## Provider API 1

- Public metadata, Node, probe, template, runtime, and feature-negotiation
  contracts.
- Distribution discovery through the `nodrix.providers` entry-point group.
- Required `nodrix-provider.json` metadata and optional detached
  `nodrix-provider.sig`.
- Metadata-only list/info operations with no provider import.
- Version, schema, feature, distribution, and entry-point consistency checks.
- Detached Ed25519 verification against a local trust store.
- Explicit production allowlist and safe POSIX trust-store permissions.
- Lazy import only after verification and only when a Node or probe is
  selected.
- Production pipeline provider verification before imports.
- Legacy adapters for current Core, Vision, Media, Recording, and ROS 2 ids.

## Unified diagnostics

The new top-level commands are:

```bash
nodrix provider list
nodrix provider info <id>
nodrix provider verify <id>
nodrix doctor
nodrix doctor --deep
nodrix doctor --json
nodrix doctor --provider ros2
```

Safe probes run by default. Device-acquiring probes require `--deep`, retain a
declared timeout/permissions contract, and report evidence through
`nodrix-doctor/1`.

## Compatibility

No 2.0 feature was removed or silently changed. Legacy doctor commands and
provider prefixes remain supported. Uninstalling an external provider leaves
Core operational; a pipeline using that provider then fails with an explicit
unknown-provider/Node diagnostic.

The 2.1 hotfix set also corrects `>=` parameter validation, empty detections
serialization, incomplete-run display in `nodrix top`, metrics disconnect
noise, and normal FFmpeg/Ctrl+C shutdown.
