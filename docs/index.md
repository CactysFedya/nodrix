# Plyctl 2.8 documentation

<div class="plyctl-hero">
<strong>Plyctl is a pipeline runtime and operations layer for modular real-time systems.</strong><br>
Version 2.8 adds multi-scope System orchestration, process isolation, transport runtime, remote target execution, and Raspberry Pi 5 ↔ workstation qualification tooling.
</div>

Plyctl lets you describe a graph once, validate it before launch, run Python or native nodes, supervise external applications, and inspect the resulting system from one CLI.

```bash
plyctl workspace init robot-project
cd robot-project
plyctl prepare
plyctl run
```

```{admonition} 2.8.0 release status
:class: note
`2.8.0` stabilizes multi-scope orchestration, process isolation, transport runtime, and authenticated remote target execution. The Raspberry Pi 5 ↔ workstation qualification harness is included; final physical hardware qualification remains a separate acceptance step.
```

```{admonition} Naming in 2.x
:class: note
`Plyctl`, the `plyctl` command, and `plyctl.dev/v2` are the current public names. The `nodrix` Python package, command, manifest identifiers, provider schemas, and `.nodrix/` state directory remain supported for compatibility throughout the 2.x series.
```

## Start here

- New user: follow [Installation](getting-started/installation.md), then [Your first workspace](getting-started/first-workspace.md).
- Pipeline author: read [Manifest API v2](reference/manifest.md) and [Python SDK](reference/python-sdk.md).
- Integration author: follow [Build a provider](tutorials/provider.md) and [Provider SDK reference](reference/provider-sdk.md).
- Robot developer: use [ROS 2 integration](integrations/ros2.md), [FAST-LIO2](integrations/fast-lio2.md), and the [FAST-LIVO2 semantic-mapping qualification page](integrations/fast-livo2-semantic-mapping.md).
- Operator: learn [Workspace operations](tutorials/workspace-operations.md), [Production operation](how-to/production.md), and [Portable deployment](how-to/portable-deployment.md).

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
how-to/portable-deployment
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
reference/stabilization-register
```

```{toctree}
:maxdepth: 2
:caption: Integrations and examples

integrations/index
integrations/ros2
integrations/fast-lio2
integrations/fast-livo2-semantic-mapping
integrations/media
examples/index
```

```{toctree}
:maxdepth: 2
:caption: Project

PRINCIPLES
COMPATIBILITY
adr/README
planning/index
releases/index
contributing/index
```

<a href="../../ru/latest/">Русская документация</a>
