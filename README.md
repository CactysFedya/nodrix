# Nodrix 2.0.0

[![PyPI](https://img.shields.io/pypi/v/nodrix.svg)](https://pypi.org/project/nodrix/)
[![Python](https://img.shields.io/pypi/pyversions/nodrix.svg)](https://pypi.org/project/nodrix/)
[![CI](https://github.com/CactysFedya/nodrix/actions/workflows/ci.yml/badge.svg)](https://github.com/CactysFedya/nodrix/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Nodrix is a high-performance typed runtime for local and distributed streaming graphs. It runs Python and C++ nodes in one graph, preserves zero-copy paths where the memory domain permits, and makes every copy, drop, restart, queue, and network export observable.


## Nodrix 2.0 highlights

Nodrix 2.0 establishes stable Manifest v2, Python SDK and Plugin C ABI 2
contracts while keeping existing Manifest v1 pipelines readable. It adds
reusable Fragments, signed offline plugins, production validation, automatic
recording, OpenTelemetry lifecycle traces, optional ROS 2 adapters, a packaged
standalone C++ runner, and direct external C ABI plugin execution in
`engine: native`.

```bash
nodrix migrate pipeline.yaml --to v2
nodrix validate pipeline.v2.yaml --production
nodrix run pipeline.v2.yaml --production
```

Multi-rate detection and tracking remain available without duplicating stale
work:

```text
source 30 FPS ─┬─ latest frame → detector ~10 FPS ─┐
               └─ every frame → realtime tracker ──┤
                                                   └─ tracks at source rate
```

```bash
nodrix init camera_app --template vision
cd camera_app
nodrix inspect
nodrix run
nodrix top
```

`vision.realtime_bytetrack` predicts on every source frame, applies each
detection once, and replays delayed measurements through bounded state history.
Native C++20 IoU association is used by the production block. Encoder and NCNN
selection are hardware-first and always expose the selected backend and any
fallback.

## Core model

```text
Pipeline manifest
       ↓ validate / lock
Executable typed graph
       ↓
Node → Port → Edge → Node
       ├─ in-process zero-copy
       ├─ shared-memory process isolation
       ├─ device-memory contracts
       └─ named LAN streams
```

No detector, tracker, camera, or fixed stage is mandatory. A graph can be `Capture → Inference → Output`, `Source → Sink`, a branched media graph, LiDAR processing, audio, or custom typed data.

## Install

Install the core runtime and CLI from PyPI:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install nodrix
nodrix --version
```

Optional media and viewer dependencies:

```bash
pip install "nodrix[viewer]"
pip install "nodrix[media]"
pip install "nodrix[vision-ncnn,media,viewer]"
```


### Raspberry Pi and offline source installation

Nodrix 2.0.0 can be built without PyPI build isolation when the runtime dependencies are already present:

```bash
python3 -m pip install . --no-build-isolation --no-deps
```

Use `scripts/install_offline.sh` for a dependency preflight. See [docs/OFFLINE_INSTALL_RU.md](docs/OFFLINE_INSTALL_RU.md).

For an isolated CLI installation:

```bash
pipx install nodrix
```

Release wheels cover Linux x86-64, Linux ARM64, macOS Apple Silicon, and
Windows x86-64. Each wheel contains the native extensions and
`nodrix/bin/nodrix-native-runner`; production execution does not compile code
on first use. When no compatible wheel exists, building the included source
distribution requires CMake, a C++20 compiler, and Python development headers.

## Empty project and templates

```bash
nodrix init my_project
```

This creates an intentionally empty project skeleton. Runnable examples are explicit:

```bash
nodrix init camera_app --template vision
nodrix init media_app --template media
nodrix init device_app --template device
nodrix init package_app --template package
```

## Run and reproduce

```bash
cd my_project
nodrix validate --strict
nodrix lock
nodrix run --locked
```

Every run receives its own artifact directory:

```text
.nodrix/runs/<run-id>/
├── manifest.yaml
├── resolved-manifest.yaml
├── nodrix.lock
├── runtime.json
├── environment.json
├── status.json
├── metrics.jsonl
├── errors.jsonl
├── logs/
├── outputs/
└── summary.json
```

## Stable Python API

```python
from nodrix import Message, Node

class Multiply(Node):
    input_types = {"input": "core.object"}
    output_types = {"output": "core.object"}

    def process(self, inputs):
        message = inputs["input"]
        return {
            "output": message.with_updates(
                payload={"value": message.payload["value"] * 2}
            )
        }
```

Nodrix 2.x preserves the public `Node`, `SourceNode`, `SinkNode`, `Message`,
`NodeContext`, manifest models, buffer, memory, error, and lifecycle contracts.
Existing nodes that override `open`, `flush`, and `close` continue to work
through lifecycle adapters.

## Lifecycle and health

Lifecycle states:

```text
created → configuring → ready → starting → running → stopping → stopped
                                      ├→ degraded / restarting
                                      └→ failed
```

```bash
nodrix status
nodrix health
nodrix health --watch
```

Process-isolated nodes can use watchdog recovery:

```yaml
nodes:
  detector:
    uses: ./nodes/detector.py:Detector
    execution:
      isolation: process
    failure:
      policy: restart_node
      max_restarts: 5
    health:
      timeout_ms: 2000
      on_timeout: restart
```

## Local packages

```bash
nodrix init my_nodes --template package
cd my_nodes
nodrix package build .
nodrix package install dist/my-nodes-1.0.0.ndpkg
```

Use an installed node by stable package reference:

```yaml
nodes:
  processor:
    uses: my-nodes/passthrough
```

`.ndpkg` installation verifies the complete member set and SHA-256 checksums
before extraction, rejects traversal/symlinks/platform filename collisions and
decompression bombs, and atomically installs immutable versions. Packages may
be signed and verified with an Ed25519 key. The local registry is offline by
design; Nodrix does not silently download or execute marketplace code.

## Secure named streams

Only explicitly exported ports become network streams. Local edges remain direct and do not pay network or serialization overhead.

```yaml
streams:
  bind_host: 0.0.0.0
  max_message_bytes: 67108864
  tls:
    enabled: true
    certificate: secrets/server.crt
    private_key: secrets/server.key
  exports:
    - name: /camera/front/h264
      from: encoder.encoded
      queue:
        capacity: 1
        policy: latest
      access:
        mode: token
        token_env: NODRIX_CAMERA_TOKEN
        allow_ips: ["192.168.1.0/24"]
```

```bash
export NODRIX_STREAM_TOKEN=...
nodrix stream echo /camera/front/h264 --ca secrets/ca.crt
nodrix-viewer /camera/front/h264
```

TLS endpoints are advertised as `nodrix+tls://`. Certificate verification is
mandatory; mutual TLS is available with `client_ca` and
`require_client_certificate`.

## Production validation

```bash
nodrix validate --strict
nodrix run --production
nodrix inspect --memory
nodrix plan pipeline.yaml
nodrix diagnose runs/RUN-ID
nodrix explain edge source.output:sink.input --pipeline pipeline.yaml
```

The validator checks graph cycles, port/type compatibility, memory transfers, unsupported copies, open LAN streams, stream backpressure, watchdog/isolation conflicts, resource configuration, and native plugin loading.

The production gate additionally requires Manifest v2 and explicit health
timeouts, rejects fallback-permitting acceleration, relative model paths,
unverified required plugins, unencrypted/open LAN exports, and planned payload
copies. Direct native libraries additionally require an absolute path inside
`security.native_plugin_allowlist` and cannot be world-writable.

`nodrix optimize` writes separate benchmark variants and a decision report. It
never edits or applies the production pipeline.

## Metrics, resources and runs

```bash
# runtime.metrics.listen can be stored in pipeline.yaml
nodrix run
nodrix top
nodrix metrics --format prometheus
nodrix runs list
nodrix runs show <run-id>
nodrix runs compare <run-a> <run-b>
```

## Plugin C ABI 2.0

```bash
nodrix native inspect ./libdetector.so
```

Plugin C ABI 2.0 uses numeric ABI `131072`, opaque handles and function
tables. C++ standard-library objects and exceptions never cross the shared
library boundary. Correlation strings and host/device memory ownership have
explicit lifetime rules. Incompatible plugins are rejected before node
creation. External source, processor, and sink plugins can execute entirely in
the standalone runner:

```yaml
runtime:
  engine: native
nodes:
  detector:
    uses: native:/opt/nodrix/plugins/libdetector.so#vision.detector
```

## Main capabilities carried into 1.0

- Python/C++ unified graph executor;
- native bounded queues and reusable buffer pools;
- shared-memory process isolation with zero-copy input/output paths;
- stable CPU, shared, DMA-BUF, CUDA, ROCm, Vulkan, OpenCL, Metal, NPU,
  DLPack, and external-memory contracts;
- DLPack interoperability;
- `.ndrx` universal record/play;
- FFmpeg Media Pack and H.264/H.265 named streams;
- low-latency `nodrix-viewer`;
- typed custom-message generation for Python and C++;
- local/LAN stream discovery without a mandatory agent.

## Honest limitations

Memory-domain contracts and planning are stable, but a declared domain is not
a built-in hardware backend. Validated paths are listed in
[docs/PLATFORM_CAPABILITIES.md](docs/PLATFORM_CAPABILITIES.md). The reference
FFmpeg source and overlay still use host BGR frames; complete V4L2 DMA-BUF
capture and CUDA IPC operators remain hardware-specific plugins. ROS 2
adapters are generic Python adapters, not a claim of loaned-message image or
PointCloud2 zero-copy. `placement` is a deployment contract, not a central
scheduler.

See [docs/BLOCKS.md](docs/BLOCKS.md),
[docs/COMPACT_MANIFEST.md](docs/COMPACT_MANIFEST.md),
[docs/PROFILES.md](docs/PROFILES.md),
[docs/RESOURCE_TELEMETRY.md](docs/RESOURCE_TELEMETRY.md),
[docs/BENCHMARKING.md](docs/BENCHMARKING.md),
[docs/MULTI_RATE_VISION.md](docs/MULTI_RATE_VISION.md),
[docs/RELEASE_2.0.0.md](docs/RELEASE_2.0.0.md),
[CONTRIBUTING.md](CONTRIBUTING.md), and
[PUBLISHING_RU.md](PUBLISHING_RU.md).
