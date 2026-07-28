# Changelog

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
