# Plyctl 2.3 documentation

<div class="plyctl-hero">
<strong>Plyctl is a pipeline runtime and operations layer for modular real-time systems.</strong><br>
Version 2.3 adds workspace contexts, reproducible environments, background operations, operational views, managed ROS 2 processes, and FAST-LIO2 integration.
</div>

Plyctl lets you describe a graph once, validate it before launch, run Python or native nodes, supervise external applications, and inspect the resulting system from one CLI.

```bash
plyctl workspace init robot-project
cd robot-project
plyctl prepare
plyctl run
```

```{admonition} Naming in 2.x
:class: note
`Plyctl`, the `plyctl` command, and `plyctl.dev/v2` are the current public names. The `nodrix` Python package, command, manifest identifiers, provider schemas, and `.nodrix/` state directory remain supported for compatibility throughout the 2.x series.
```

## Start here

- New user: follow [Installation](getting-started/installation.md), then [Your first workspace](getting-started/first-workspace.md).
- Pipeline author: read [Manifest API v2](reference/manifest.md) and [Python SDK](reference/python-sdk.md).
- Integration author: follow [Build a provider](tutorials/provider.md) and [Provider SDK reference](reference/provider-sdk.md).
- Robot developer: use [ROS 2 integration](integrations/ros2.md) and [FAST-LIO2](integrations/fast-lio2.md).
- Operator: learn [Workspace operations](tutorials/workspace-operations.md) and [Production operation](how-to/production.md).

```{toctree}
:maxdepth: 2
:caption: Getting started

getting-started/index
getting-started/installation
getting-started/first-workspace
getting-started/first-pipeline
getting-started/next-steps
```

```{toctree}
:maxdepth: 2
:caption: Tutorials

tutorials/index
tutorials/workspace-operations
tutorials/python-node
tutorials/provider
tutorials/ros2-fastlio2
```

```{toctree}
:maxdepth: 2
:caption: How-to guides

how-to/index
how-to/environments
how-to/background
how-to/debug
how-to/production
```

```{toctree}
:maxdepth: 2
:caption: Concepts

concepts/index
concepts/workspaces
concepts/runtime
concepts/providers
```

```{toctree}
:maxdepth: 2
:caption: Reference

reference/index
reference/cli
reference/workspace
reference/manifest
reference/python-sdk
reference/provider-sdk
reference/plugin-sdk
reference/compatibility
```

```{toctree}
:maxdepth: 2
:caption: Integrations and examples

integrations/index
integrations/ros2
integrations/fast-lio2
integrations/media
examples/index
```

```{toctree}
:maxdepth: 2
:caption: Project

releases/index
contributing/index
```
