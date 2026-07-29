# Changelog

## 1.7.0 — Crash-safe NDRX2 and Run Provenance
- Added NDRX2 checkpoint chunks with bounded in-memory indexes and per-chunk SHA-256 integrity.
- Made finalized checkpoints readable independently of the final summary.
- Added recovery of complete records from an interrupted active chunk while refusing checksum corruption.
- Added `nodrix recording repair` to copy recovered data into a finalized file without overwriting the source.
- Preserved read compatibility with NDRX1 recordings.
- Added packet, metadata and index limits to recording readers.
- Added `hardware.json`, `plugins.json` and `models.json` to every unified run.
- Included local implementation and model file sizes and SHA-256 hashes in provenance artifacts.

## 1.6.0 — Deterministic Planning and Plugin C ABI 2.0
- Added deterministic, secret-free `nodrix.execution-plan/v1` documents with graph hashes, resolved order, resources, memory/copy decisions and reproducibility warnings.
- Added `nodrix inspect --plan` and persisted the same validated plan with every run.
- Replaced the C++ object boundary with Plugin C ABI 2.0: fixed-width values, opaque handles, sized structures and function tables.
- Added explicit buffer ownership callbacks for zero-copy native pass-through without allocator coupling.
- Added a C++20 convenience adapter that remains entirely inside the plugin.
- Updated native scaffolding, examples and inspection for ABI 2.0.
- Restricted the standalone native runner to built-in `native.*` nodes; external ABI 2.0 plugins use the unified executor.
- Removed the old `nodrix::Node*` plugin header and loader path.

## 1.5.1 — Safety and Reproducibility Hardening
- Made optional Vision, Media and Recording providers lazy so Core remains usable without NumPy or OpenCV.
- Made every manifest model reject unknown fields and unsupported API versions.
- Implemented and validated explicit optional-input declarations.
- Added side-effect-free built-in parameter validation before nodes or hardware are opened.
- Extended lock verification to dependencies, Python ABI, implementation, machine and Plugin ABI.
- Bound streams and generated metrics endpoints to loopback by default.
- Bounded stream handshakes and clients, fixed fragmented TCP handshakes and rejected credentials in stream URIs.
- Persisted runtime events and the resolved execution plan in every run directory.
- Applied graceful shutdown deadlines after finite sources finish, on errors and on interruption.
- Added native-tracking import checks to CI and installed-wheel smoke tests.

## 1.5.0 — Multi-rate Vision and Hardware-first Runtime
- Added `vision.realtime_bytetrack`, driven by every source frame with slower detections as a latest side input.
- Added bounded delayed-measurement replay, detector-result deduplication, prediction score decay and explicit too-old policies.
- Added a compiled C++20 IoU-association extension and a required native tracker backend in the production block.
- Added NCNN `auto|cpu|vulkan` backend selection and explicit acceleration policies.
- Added hardware-first FFmpeg adapters for VideoToolbox, V4L2 M2M, Rockchip MPP, NVENC/NVMPI, QSV/VAAPI and AMF, with required, preferred and disabled policies and no hidden fallback.
- Upgraded `inspect` to a graph-oriented view and added details and per-node modes.
- Upgraded `run` to print actual lifecycle events and selected runtime backends.
- Reworked `top` into a compact htop-style view and separated stale skips, overflow and synchronization misses.
- Added manifest-configured HTTP metrics so the reference project starts with `nodrix run`.
- Updated the Vision template to a 30 FPS multi-rate graph with block-local configuration and LAN discovery.
- Documented host-BGR, device-memory and Raspberry Pi 5 encoder limitations honestly.

## 1.4.1 — Runtime UX and Vision Hardening
- Kept normal Vision parameters inside self-contained block YAML files.
- Added comments to generated source, preprocessing, detector, tracker, overlay and encoder blocks.
- Aligned generated source rate to 15 FPS and changed the NCNN default to three threads.
- Added a bounded four-frame source history for exact-sequence overlay.
- Added compact graph inspection, per-node inspection and parameter documentation.
- Added startup and encoder-selection output to `nodrix run`.
- Reworked `nodrix top` to update one Rich Live display and separated process resources from node busy time.
- Treated normal publisher shutdown as viewer end-of-stream.
- Hid unreliable exact latency for chunked H.264/H.265 transport.
- Removed unused `configs/` and `native/` directories from the ordinary Vision template.

## 1.4.0 — Benchmark and Reproducibility
- Added the versioned `nodrix.benchmark/v1` benchmark specification and named variants.
- Separated warm-up runs from measured runs and retained every runtime artifact.
- Added P50/P95/P99 aggregation, source/sink rates, end-to-end latency, drops, errors, memory and temperature summaries.
- Added filtered environment snapshots and SHA-256 model inventory for benchmark suites.
- Expanded `runs compare` while preserving the existing node and duration delta fields.
- Added `nodrix replay` eligibility checks and safe automatic replay for captured `.ndrx` inputs.
- Preserved Nodrix 1.x manifests, reusable blocks, Node API, Plugin ABI 1.0, wire protocol and `.ndrx` format.
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
