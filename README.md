# Nodrix / Plyctl

<p align="center">
  <strong>English</strong> · <a href="docs/README.ru.md">Русский</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/plyctl/"><img alt="PyPI" src="https://img.shields.io/pypi/v/plyctl.svg"></a>
  <a href="https://www.python.org/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/plyctl.svg"></a>
  <a href="https://github.com/CactysFedya/nodrix/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/CactysFedya/nodrix/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
</p>

**Nodrix** is an experimental execution platform for describing and running heterogeneous real-time systems as one explicit, reproducible system model.

The public Python distribution and primary CLI are currently named **Plyctl**. The repository keeps the `nodrix` import/CLI and compatibility contracts throughout the 2.x line.

The project is aimed at systems where Python, C++, ROS 2, native processes, devices, transports, and edge hardware need to work together without hiding execution decisions behind application-specific glue code.

## At a glance

- **Current release:** `2.8.0`.
- **Languages:** Python 3.11+ and C++20.
- **Model:** typed YAML graph with nodes, resources, applications and transported edges.
- **Runtime:** local/native execution, process isolation, bounded queues and explicit lifecycle/health.
- **Integrations:** modular ROS 2 and spatial/mapping packages rather than ROS-specific core logic.
- **Observability:** runs, metrics, logs, errors, artifacts and execution diagnostics.
- **Platforms:** Linux x86-64/ARM64, macOS Apple Silicon and Windows x86-64 release targets.
- **Edge validation:** Raspberry Pi 5 / Ubuntu 24.04 / ROS 2 Jazzy hardware smoke is part of the release evidence.

## Why this project exists

A real robotics or computer-vision application is rarely just one algorithm:

```text
sensor driver -> preprocessing -> inference -> tracking -> mapping -> output
       |              |              |            |          |
      ROS 2          C++          Python        native      network
```

Traditional projects often encode this topology in launch scripts, shell scripts, implicit process rules and framework-specific configuration.

Nodrix/Plyctl moves those decisions into an explicit executable system description:

```text
System description
       |
       v
 validation + resolution
       |
       v
 execution plan
       |
       v
 runtime / backend
       |
       +--> Python nodes
       +--> C++ / native plugins
       +--> managed applications
       +--> ROS 2 integrations
       +--> local / network transports
       |
       v
 run state + metrics + logs + artifacts
```

The goal is not to replace ROS 2, inference frameworks or algorithms. The goal is to provide one execution model around them.

## Core ideas

### One explicit system model

The YAML description captures what runs, how components are connected and which resources or transports they require.

```yaml
applications:
  lidar_driver:
    uses: ros2.launch
    bindings: {session: ros}
    package: example_driver
    launch_file: driver.launch.py

nodes:
  mapping:
    uses: ./nodes/mapping.py:MappingNode

edges:
  - from: lidar_driver.points
    to: mapping.points
    transport:
      uses: ros2.topic
      parameters:
        topic: /points
        message_type: sensor_msgs/msg/PointCloud2
```

### Runtime decisions stay visible

The runtime is designed around explicit contracts for:

- queue capacity and backpressure;
- copies and memory domains;
- process isolation;
- lifecycle and health;
- retries/restarts and failure handling;
- local versus exported network paths;
- run artifacts and diagnostics.

### Integrations stay modular

ROS 2, mapping and spatial functionality are packaged as integrations around the core model. This keeps the execution model usable for non-ROS systems as well.

## Main capabilities

- Python SDK and CLI;
- native C++20 runner and Plugin C ABI 2;
- typed node/port/edge graph execution;
- bounded queues and reusable buffer pools;
- shared-memory process isolation;
- CPU/device-memory contracts and DLPack interoperability;
- named local/LAN streams with explicit export;
- recording and reproducible run artifacts;
- lifecycle, health and resource telemetry;
- provider discovery and verification;
- ROS 2 adapters and managed applications;
- planner/diagnose/explain tooling;
- benchmark and run comparison workflows.

## Install

For the CLI:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install plyctl
plyctl --version
```

The compatibility command remains available in the 2.x line:

```bash
nodrix --version
```

Optional integrations are installed separately, for example:

```bash
pip install plyctl-spatial plyctl-ros2 plyctl-spatial-ros2
```

## Minimal workflow

```bash
plyctl init my_project
cd my_project

plyctl validate --strict
plyctl lock
plyctl run --locked

plyctl status
plyctl health
```

For inspection and diagnostics:

```bash
plyctl plan pipeline.yaml
plyctl diagnose runs/RUN-ID
plyctl explain edge source.output:sink.input --pipeline pipeline.yaml
```

## Reproducible runs

Each run owns an artifact directory rather than relying only on console output:

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

This makes execution state, parameters and results easier to inspect and compare after the process has finished.

## ROS 2 and edge use

Nodrix/Plyctl does not fork or replace ROS 2. ROS 2 remains the middleware/data plane where appropriate, while the system model describes how ROS applications and non-ROS components belong to the same executable system.

The current release metadata includes Raspberry Pi 5 / Ubuntu 24.04 / ROS 2 Jazzy hardware smoke. Semantic mapping remains explicitly experimental rather than being presented as production-ready.

## Project status

`2.8.0` is alpha software. The repository contains production-oriented contracts and qualification tooling, but not every declared hardware memory path is implemented by the core itself.

Important limitations are documented rather than hidden behind automatic fallback. Hardware-specific acceleration, zero-copy paths and ROS 2 message behavior depend on the selected integration/backend and platform.

## Documentation

- [Documentation site](https://cactysfedya.github.io/nodrix/)
- [Changelog](CHANGELOG.md)
- [Platform capabilities](docs/PLATFORM_CAPABILITIES.md)
- [Benchmarking](docs/BENCHMARKING.md)
- [Provider API](docs/PROVIDER_API.md)
- [Contributing](CONTRIBUTING.md)

## License

Apache License 2.0. See [LICENSE](LICENSE).
