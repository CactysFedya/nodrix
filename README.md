# Nodrix

**Executable System Architecture Platform** for describing, planning, executing, and observing heterogeneous software systems.

[English](README.md) · [Русский](README.ru.md) · [Documentation](https://cactysfedya.github.io/nodrix/)

[![CI](https://github.com/CactysFedya/nodrix/actions/workflows/ci.yml/badge.svg)](https://github.com/CactysFedya/nodrix/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](pyproject.toml)
[![C++](https://img.shields.io/badge/C%2B%2B-20-blue.svg)](src/nodrix/native)

Nodrix treats a running application as **one executable system model** instead of a collection of unrelated launch scripts, configuration files, processes, ROS 2 nodes, benchmarks, and logs.

`plyctl` is the command-line interface. The repository and internal compatibility namespace retain the historical `nodrix` name.

> **Development status**
>
> `main` contains the current post-2.8 development line, including the direct System runtime work developed through the internal 2.24 milestone. Published package metadata still reports `2.3.0b1`; the next public release has not been cut yet.

## The idea

A Nodrix `System` describes the architecture that should exist at runtime:

- targets and execution context;
- resources and shared dependencies;
- applications and executable nodes;
- typed graph connections;
- interfaces and composition boundaries;
- execution policy;
- observability and reproducibility metadata.

The same definition is used by validation, planning, execution, diagnostics, and historical Run records.

```text
System Definition
       │
       ▼
   validation
       │
       ▼
Execution Plan
       │
       ▼
direct runtime materialization
       │
       ├── providers / resources
       ├── nodes / applications
       ├── graph connections
       └── execution environment
       │
       ▼
      Run
       │
       ├── lifecycle events
       ├── typed metrics
       ├── logs
       ├── artifacts
       └── immutable execution record
```

The central design rule is simple:

> **Describe the system once; derive execution from that model.**

## Why Nodrix exists

Robotics and real-time projects often accumulate separate mechanisms for:

- launching Python and C++ components;
- ROS 2 processes;
- local and device-specific configuration;
- environment setup;
- datasets and artifacts;
- tests and benchmarks;
- runtime monitoring;
- experiment history.

Nodrix brings those concerns under explicit contracts instead of hiding them in shell scripts and application-specific glue.

It is not a replacement for ROS 2, Docker, CMake, or a machine-learning framework. It is the layer that describes **how independent components form one executable system**.

## Canonical execution model

Current development is system-first:

```text
Definition
    ↓
Operation
    ↓
Planner
    ↓
Plan
    ↓
Executor
    ↓
Execution Record
    ↓
Run / History
```

Important architectural properties:

- **plan before execution** — runtime behavior is resolved explicitly;
- **no hidden fallback** — fallback and compatibility behavior must be visible;
- **backend-neutral contracts** — system semantics are separate from execution mechanics;
- **authoring is separate from runtime** — SDKs describe definitions; they do not own execution;
- **Run is canonical** — test, benchmark, diagnostics, and normal execution share the same execution/history model;
- **observability is structured** — Events, Metrics, Logs, and Artifacts are distinct entities.

## System model

A simplified system can look like this:

```yaml
apiVersion: nodrix.system/v1
kind: System
metadata:
  name: mapping-stack

targets:
  robot:
    platform: linux-aarch64

resources:
  ros:
    uses: ros2.session

applications:
  lidar:
    target: robot
    uses: ros2.launch
    bindings:
      session: ros

  mapping:
    target: robot
    uses: process

graph:
  edges:
    - from: lidar.points
      to: mapping.points
```

The exact schema is defined in [`src/nodrix/schemas/system-v1.schema.json`](src/nodrix/schemas/system-v1.schema.json).

## Direct System runtime

The current development line moves System execution away from reconstructing legacy pipeline manifests and toward direct materialization of the planned architecture.

Relevant implementation areas include:

```text
src/nodrix/system/
├── planning.py
├── canonical_runtime.py
├── direct_preparation.py
├── direct_materialization.py
├── direct_node_preparation.py
├── direct_node_materialization.py
├── direct_provider_materialization.py
├── direct_edge_materialization.py
├── direct_environment.py
├── direct_executor.py
├── connection_execution.py
├── runtime_mechanics.py
└── validation.py
```

Runtime-neutral primitives live outside the System frontend where appropriate, including node loading, process isolation realization, graph validation, provider materialization, edge materialization, and transport bindings.

## Run model and observability

Nodrix models execution history as a first-class part of the architecture.

A Run can persist:

```text
.nodrix/runs/<run-id>/
├── definition / plan snapshots
├── status
├── execution events
├── metrics
├── logs
├── artifacts
└── final record
```

The model supports:

- append-only lifecycle events;
- bounded and redactable logs;
- typed metrics;
- execution policy and observability profiles;
- immutable final records;
- recovery and integrity validation;
- structured Run comparison;
- benchmarks expressed as normal Runs plus aggregate comparison results.

## SDK and extensibility

The Python SDK is an **authoring surface**, not a second runtime.

It exposes canonical identities and definitions for:

- System authoring;
- Workflow authoring;
- Operations;
- custom Definitions;
- extension planners/executors;
- typed messages and resources.

The goal is multiple authoring frontends converging on one canonical execution path.

## Robotics and ROS 2

ROS 2 integration is modular. Nodrix can describe ROS sessions and applications without making ROS 2 part of the core object model.

The repository contains integration work for real robotics pipelines, including FAST-LIVO2 / LiDAR mapping scenarios and Raspberry Pi 5 qualification work. These are integration cases built on the same System model rather than special-case runtime modes.

## Repository map

```text
src/nodrix/
├── system/          # System model, planner, validation, direct runtime
├── model/           # canonical object model
├── sdk/             # authoring APIs
├── native/          # C++20 runtime/native components
├── run_*.py         # Run persistence, recovery, metrics, logs, comparison
├── benchmark_*.py   # benchmark execution and aggregation
└── ...

packages/
├── nodrix-ros2/
├── nodrix-mapping/
├── nodrix-mapping-ros2/
└── compatibility/integration packages

docs/                # English/Russian documentation and ADRs
tests/               # architecture, runtime and compatibility tests
examples/             # runnable examples
```

## Installation

The currently published package is named `plyctl`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install plyctl
plyctl --version
```

For development from this repository:

```bash
git clone https://github.com/CactysFedya/nodrix.git
cd nodrix
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Basic CLI

Typical system-oriented commands are:

```bash
plyctl system validate path/to/system.yaml
plyctl system plan path/to/system.yaml
plyctl system show path/to/system.yaml
plyctl system run path/to/system.yaml
```

The repository also contains CLI surfaces for projects, Runs, operations, benchmarks, diagnostics, and development tooling.

## Testing

The project has a broad regression suite covering the canonical model, planning/execution boundaries, System composition, direct runtime materialization, Run persistence, metrics, benchmarking, SDK authoring, compatibility, and integrations.

Typical local checks:

```bash
python -m ruff check src tests scripts
python -m pytest -q
```

Some integration and platform qualification tests require additional dependencies or hardware.

## Documentation

Key starting points:

- [`docs/index.md`](docs/index.md)
- [`docs/PRINCIPLES.md`](docs/PRINCIPLES.md)
- [`docs/ROADMAP.md`](docs/ROADMAP.md)
- [`docs/CANONICAL_OBJECT_MODEL.md`](docs/CANONICAL_OBJECT_MODEL.md)
- [`docs/CANONICAL_STORAGE_STANDARD.md`](docs/CANONICAL_STORAGE_STANDARD.md)
- [`docs/adr/`](docs/adr/)
- [`docs/ru/`](docs/ru/)

## Project status

Nodrix is an actively developed architecture/runtime project. The repository contains both stable released compatibility surfaces and newer architecture work that has not yet been packaged as a public release.

For that reason:

- do not interpret the internal milestone number as a PyPI release version;
- integration examples may require platform-specific dependencies;
- some historical compatibility code remains intentionally present during the 2.x transition.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
