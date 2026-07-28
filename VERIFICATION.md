# Nodrix 1.0.0 verification

Verified on Linux x86-64 with CPython 3.13 and GCC 14.2.

## Automated tests

- Python unit/integration tests: **59 passed**.
- Native C++ Release CTest: **1/1 passed**.
- AddressSanitizer + UndefinedBehaviorSanitizer C++ CTest: **1/1 passed**.
- Native extensions built and imported:
  - `_native_queue`;
  - `_native_buffer`;
  - `_native_device`;
  - `_native_plugin`.

## Production runtime

Verified:

- lifecycle reaches `stopped` after graceful draining;
- watchdog interrupts and restarts a deliberately hung process-isolated node;
- `restart`, `skip_message` and independent branch shutdown behavior;
- run artifacts, `status.json`, `metrics.jsonl`, summaries and redacted resolved manifests;
- resource and message-size configuration paths;
- strict validation of graph cycles, memory plans, open LAN streams and unsafe watchdog settings;
- token authentication and IP/CIDR stream access controls;
- schema versions in the wire protocol;
- missing token values do not block static validation, but do block stream publication at runtime.

All runnable built-in templates (`core`, `vision`, `media`, `network`, `benchmark`, `data-plane`, `device`) passed `nodrix validate --strict`. Ordinary templates bind streams to localhost by default; the explicit `network` template requires `NODRIX_STREAM_TOKEN`.

## Lock files and packages

Verified:

- deterministic `nodrix.lock` creation and verification;
- checksum mismatch detection after modifying tracked content;
- `.ndpkg` build, safe-path validation, SHA-256 verification and local installation;
- installed `package/node` resolution;
- package list/info/remove command paths.

## Metrics and run history

A live pipeline was started with:

```bash
nodrix run --metrics-listen 127.0.0.1:19464
```

Both endpoints were queried successfully while the graph was running:

- `/metrics` — Prometheus text;
- `/metrics.json` — node and edge snapshot.

Run list/show and final summary inspection were also verified from an installed wheel.

## Native ABI 1.0

- Plugin ABI: **1.0 (`65536`)**.
- Runtime ABI: **1.0 (`65536`)**.
- Compatibility check: **yes**.
- Feature flags: typed ports and memory-domain contracts (`0x3`).
- Mixed Python → C++ → Python video graph completed with **60 frames**.

Plugins built for the experimental 0.9 ABI 3 must be rebuilt for ABI 1.0.

## Stress and parser checks

Local bounded stress checks completed successfully:

- malformed wire inputs: **5000 rejected, 0 accepted, no crash**;
- authenticated stream reconnects: **200/200**;
- production graph repetitions: **50 runs × 1000 messages**.

These are release-gate stress checks, not a 24-hour soak test.

## Wheel verification

The Linux CPython 3.13 wheel was installed into a separate virtual environment, outside the source tree.

Verified from the installed wheel:

- `nodrix --version` returned `Nodrix 1.0.0`;
- all four native extensions loaded from `site-packages`;
- ordinary `nodrix init` created an empty project;
- `core` template passed strict validation;
- `nodrix lock`, `lock --check` and `run --locked` completed;
- run history commands worked;
- package template built and installed a `.ndpkg` package;
- Media Pack created a valid H.264 640×360 stream;
- `nodrix-viewer` decoded 20/20 requested frames with zero decode errors.

## Source distribution verification

The source `tar.gz` was installed into a second separate virtual environment with build isolation disabled because the execution environment's internal package index did not provide the required build/runtime packages.

Verified from the installed source package:

- all four native extensions rebuilt and imported;
- `nodrix --version` returned `Nodrix 1.0.0`;
- the generated `device` project passed strict validation;
- `nodrix inspect --memory` reported the shared-memory path;
- the isolated source produced **32 zero-copy outputs** with **0 output payload copies**.

Third-party runtime dependencies were exposed from the host Python environment only because the internal package index was unavailable. Nodrix itself and its native modules came from the release wheel/source package.

## Security scope

Verified security controls include token authentication, IP/CIDR allowlists, parser size limits, schema validation, safe `.ndpkg` extraction and artifact secret redaction.

Nodrix 1.0 does **not** yet claim:

- TLS certificate transport;
- sandboxing of trusted native machine code;
- signed public marketplace packages;
- remote code installation.

## Hardware-specific scope

Contracts and diagnostics exist, but full hardware backends were not claimed or hardware-validated for:

- CUDA IPC mapping and synchronization;
- complete V4L2 DMA-BUF capture/requeue;
- CUDA/Vulkan/OpenCL/NPU importers;
- native libav decode/encode nodes;
- automatic CPU↔device conversion nodes;
- QUIC/UDP native transport.

## Long-running scope

A true 24-hour hardware soak test was not performed in this environment. Before deploying on a robot or UAV, run the supplied stress scripts and a target-specific soak test with the actual camera, accelerator, encoder, network and storage configuration.
