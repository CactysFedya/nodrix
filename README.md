# Nodrix 1.2.0

[![PyPI](https://img.shields.io/pypi/v/nodrix.svg)](https://pypi.org/project/nodrix/)
[![Python](https://img.shields.io/pypi/pyversions/nodrix.svg)](https://pypi.org/project/nodrix/)
[![CI](https://github.com/CactysFedya/nodrix/actions/workflows/ci.yml/badge.svg)](https://github.com/CactysFedya/nodrix/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Nodrix is a high-performance typed runtime for local and distributed streaming graphs. It runs Python and C++ nodes in one graph, preserves zero-copy paths where the memory domain permits, and makes every copy, drop, restart, queue, and network export observable.


## Nodrix 1.2 highlights

Keep the graph readable and move replaceable node settings into `blocks/`:

```yaml
name: raspberry-vision
profile: realtime-low-latency

blocks:
  camera: blocks/camera.yaml
  detector: blocks/detectors/yolo26n-320.yaml
  output: blocks/outputs/lan-preview.yaml

flow:
  - camera.frame -> detector.frame
  - camera.frame -> output.frame
  - detector.detections -> output.detections
```

```yaml
# blocks/detectors/yolo26n-320.yaml
use: vision.ncnn_detector
model: models/yolo26n-320.ncnn
imgsz: 320
conf: 0.18
```

```bash
nodrix block list
nodrix block inspect blocks/detectors/yolo26n-320.yaml
nodrix validate --block detector=blocks/detectors/rtdetr-640.yaml
nodrix run --block detector=blocks/detectors/rtdetr-640.yaml \
  --set detector.conf=0.12
nodrix inspect --resolved
```

Blocks are expanded before validation and graph construction. They do not add
processes, queues, copies, or serialization boundaries.

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
```


### Raspberry Pi and offline source installation

Nodrix 1.2.0 can be built without PyPI build isolation when the runtime dependencies are already present:

```bash
python3 -m pip install . --no-build-isolation --no-deps
```

Use `scripts/install_offline.sh` for a dependency preflight. See [docs/OFFLINE_INSTALL_RU.md](docs/OFFLINE_INSTALL_RU.md).

For an isolated CLI installation:

```bash
pipx install nodrix
```

GitHub Releases provide prebuilt Linux x86-64, Linux ARM64 and macOS Apple Silicon wheels. When a compatible wheel is unavailable, `pip` builds the included C++20 extensions from the source distribution, which requires a C++ compiler and Python development headers.

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

Nodrix 1.x preserves the public `Node`, `SourceNode`, `SinkNode`, `Message`, `NodeContext`, buffer, memory, and lifecycle contracts. Existing 0.x nodes that override `open`, `flush`, and `close` continue to work through lifecycle adapters.

## Lifecycle and health

Lifecycle states:

```text
created → configured → starting → running → draining → stopping → stopped
                                      └→ failed / restarting
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
      policy: restart
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

`.ndpkg` installation checks archive paths and SHA-256 checksums. No public marketplace or remote-code installation is enabled in 1.0.

## Secure named streams

Only explicitly exported ports become network streams. Local edges remain direct and do not pay network or serialization overhead.

```yaml
streams:
  bind_host: 0.0.0.0
  max_message_bytes: 67108864
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
nodrix stream echo /camera/front/h264
nodrix-viewer /camera/front/h264
```

## Production validation

```bash
nodrix validate --strict
nodrix inspect --memory
```

The validator checks graph cycles, port/type compatibility, memory transfers, unsupported copies, open LAN streams, stream backpressure, watchdog/isolation conflicts, resource configuration, and native plugin loading.

## Metrics, resources and runs

```bash
nodrix run --metrics-listen 127.0.0.1:9464
nodrix top
nodrix metrics --format prometheus
nodrix runs list
nodrix runs show <run-id>
nodrix runs compare <run-a> <run-b>
```

## Native ABI 1.0

```bash
nodrix native inspect ./libdetector.so
```

Nodrix Plugin ABI 1.0 uses numeric ABI `65536` and feature flags for typed ports and memory-domain contracts. Incompatible plugins are rejected before node creation.

## Main capabilities carried into 1.0

- Python/C++ unified graph executor;
- native bounded queues and reusable buffer pools;
- shared-memory process isolation with zero-copy input/output paths;
- CPU, shared, DMA-BUF, CUDA, ROCm, Vulkan, OpenCL, Metal, NPU and external-memory contracts;
- DLPack interoperability;
- `.ndrx` universal record/play;
- FFmpeg Media Pack and H.264/H.265 named streams;
- low-latency `nodrix-viewer`;
- typed custom-message generation for Python and C++;
- local/LAN stream discovery without a mandatory agent.

## Honest limitations

Nodrix 1.0 stabilizes the contracts and production control plane. Hardware-specific CUDA IPC mapping, full V4L2 DMA-BUF capture/requeue, native libav nodes, QUIC/UDP data plane, TLS certificates, ROS 2 bridge, and ready-made detector/tracker packs remain later backends or releases.

See [docs/BLOCKS.md](docs/BLOCKS.md), [docs/COMPACT_MANIFEST.md](docs/COMPACT_MANIFEST.md), [docs/PROFILES.md](docs/PROFILES.md), [docs/RESOURCE_TELEMETRY.md](docs/RESOURCE_TELEMETRY.md), [docs/RELEASE_1.2.0.md](docs/RELEASE_1.2.0.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [PUBLISHING_RU.md](PUBLISHING_RU.md).
