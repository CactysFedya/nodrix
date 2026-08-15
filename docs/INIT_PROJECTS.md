# `nodrix init` in 1.0.0

## Empty project

```bash
nodrix init my_project
```

Creates the full directory structure but no example algorithm:

```text
my_project/
├── nodrix.toml
├── pipeline.yaml          # intentionally empty nodes/edges
├── nodes/__init__.py
├── configs/default.yaml
├── types/
├── models/
├── data/
├── outputs/
├── tests/
├── native/
├── scripts/
├── docs/
├── requirements.txt
├── README.md
└── .gitignore
```

The empty manifest is not runnable until at least one node is added. This is intentional: a normal project should not contain sample detector, tracker or source code that the user must later delete.

## Explicit templates

```bash
nodrix init app --template core
nodrix init app --template vision
nodrix init app --template media
nodrix init app --template network
nodrix init app --template data-plane
nodrix init app --template benchmark
nodrix init robot --template ros2
```

Templates contain actual Python implementations, tests, manifests and an
optional C++ plugin example. Installed providers may also publish templates;
they appear in the same `--template` namespace. Provider templates are copied
from validated package metadata without importing provider code.

## Replacing an empty skeleton

```bash
nodrix init my_project --template vision --force
```

`--force` only overwrites generated paths; use it carefully if the directory already contains user code.

## Device template

```bash
nodrix init device_demo --template device
```

Creates a process-isolated source that writes into executor-owned shared output buffers. Use `nodrix inspect --memory` and `nodrix inspect --live` to verify zero output copies.
