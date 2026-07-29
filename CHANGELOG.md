# Changelog
## 1.3.0 — Production Vision Vertical Slice
- Added built-in letterbox preprocessing with reversible source-coordinate metadata.
- Added an optional NCNN detector with common modern and legacy YOLO output decoding.
- Added deterministic NumPy NMS, class filtering, and source-frame box restoration.
- Added a ByteTrack-style two-stage IoU tracker with bounded Kalman state.
- Added tracked-object overlay and a complete RTSP/video-to-H.264 reference pipeline.
- Added the `vision-ncnn` optional dependency group, Vision Pack documentation, and fake-backend CI tests.
- Preserved Nodrix 1.x manifests, blocks, message contracts, Node API, wire protocol, and native runtime behavior.
## 1.2.1 — Cross-platform stabilization
- Fixed `multiprocessing.shared_memory` compatibility across Python 3.11–3.14.
- Added portable deterministic POSIX shared-memory names for macOS.
- Added macOS physical-memory telemetry fallback through `sysctl`.
- Removed duplicate native-extension rebuild instructions after editable installation.
- Added native runner version consistency, native end-to-end CI, and ASan/UBSan coverage.
- Added regression tests for shared-memory lifecycle and platform fallbacks.
- Preserved the canonical manifest, public Node API, Plugin ABI 1.0, wire protocol, and runtime semantics.

## 1.2.0 — Reusable Blocks

- Added top-level `blocks:` for reusable single-node YAML configurations.
- Added repeatable `--block name=path.yaml` replacement to run, validate, inspect, benchmark, and config commands.
- Added short block parameter overrides such as `--set detector.conf=0.12`.
- Added `nodrix block list` and `nodrix block inspect` with JSON output.
- Added exact imported-block checksums to `nodrix.lock`; unused alternatives are not locked.
- Updated the vision template to demonstrate organized camera, detector, and output blocks.
- Preserved the canonical manifest, public Node API, Plugin ABI 1.0, wire protocol, and runtime performance.

## 1.1.0 — Compact configuration and resource telemetry

- Added compact manifests with `use`, direct node parameters, `flow`, and `publish`.
- Added `realtime-low-latency`, `realtime-balanced`, `lossless-recording`, `maximum-throughput`, and `debug` profiles.
- Added `--profile`, repeatable `--set`, `inspect --resolved`, and `config show/explain/profiles`.
- Added `encoder: auto`, runtime FFmpeg encoder probes, and `media select-encoder`.
- Added per-node CPU/RSS/shared-buffer/queue telemetry and the live `nodrix top` command.
- Added publisher bitrate, drops, subscriber count, node CPU and temperature to the Viewer overlay.
- Preserved Plugin ABI 1.0, wire protocol, `.ndrx`, `.ndpkg`, lock-file and public Node API compatibility.

## 1.0.1 — Packaging and installation stabilization

- Fixed the PyPI release matrix by publishing supported Linux x86-64, Linux ARM64 and macOS Apple Silicon wheels without the failing macOS Intel job.
- Updated official GitHub Actions to Node.js 24 based versions.
- Pinned cibuildwheel 3.4.1 for reproducible releases.
- Reduced the source-build requirement to `setuptools>=68` and moved license-file discovery to stable setuptools metadata.
- Added offline-installation tooling and Raspberry Pi documentation.
- Kept the public API, Plugin ABI 1.0, pipeline schema and runtime behavior unchanged.

## 1.0.0 — Production Runtime

- Fixed the public Python API for the Nodrix 1.x line.
- Introduced lifecycle states, readiness/health snapshots, queue pressure, watchdog recovery, graceful shutdown, `skip_message`, `disable_branch`, and process resource limits.
- Declared stable Nodrix Plugin ABI 1.0 (`65536`) with typed-port and memory-domain feature flags.
- Added `nodrix native inspect` compatibility checks.
- Added checksummed local `.ndpkg` packages and `package/node` references.
- Added deterministic `nodrix.lock`, `nodrix lock --check`, and `nodrix run --locked`.
- Added schema versions to the wire protocol and generated custom types.
- Added production run artifacts, `status`, `health`, `metrics`, and `runs` commands.
- Added JSONL telemetry and optional Prometheus HTTP endpoint.
- Added token-authenticated/IP-allowlisted streams, handshake/message limits, strict validation, and automatic secret redaction.
- Added package, lock, security, lifecycle, watchdog, and failure-policy integration tests.

## 0.9.0 — Device Memory & Native I/O foundation

- Universal device-memory contracts, DLPack, DMA-BUF descriptors, isolated source support, and zero-copy process outputs.

## 0.8.0 — Data Plane

- Shared memory, process isolation, `.ndrx` record/play, and H.264/H.265 streams.

## 0.7.0 — Media Pack

- FFmpeg sources/writers, persistent encoders, media CLI, and viewer FFmpeg mode.
