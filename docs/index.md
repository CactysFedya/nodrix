# Plyctl 2.3 documentation

<div class="plyctl-hero">
<strong>Nodrix is an executable system architecture platform for heterogeneous real-time and engineering systems.</strong><br>
`plyctl` is the command-line interface for authoring, validating, planning, executing, and operating those systems.
</div>

The canonical `System` model represents targets, resources, applications,
computation graphs, relations, and execution context as one executable
architecture. The original 2.x Pipeline model remains available as a
specialized dataflow and compatibility surface.

```bash
plyctl workspace init robot-project
cd robot-project
plyctl prepare
plyctl run
```

```{admonition} 2.3.0b1 beta status
:class: note
`2.3.0b1` stabilizes local Python node loading, release metadata, and bilingual documentation. The FAST-LIVO2 semantic-mapping vertical slice has Raspberry Pi 5 hardware-smoke evidence but remains experimental until its release blockers are closed.
```

```{admonition} Naming in 2.x
:class: note
`Plyctl`, the `plyctl` command, and `plyctl.dev/v2` are the current public names. The `nodrix` Python package, command, manifest identifiers, provider schemas, and `.nodrix/` state directory remain supported for compatibility throughout the 2.x series.
```

## Start here

- New user: follow [Installation](getting-started/installation.md), then [Your first workspace](getting-started/first-workspace.md).
- System author: start with the canonical System model and project resources.
- 2.x Pipeline author: read [Manifest API v2](reference/manifest.md) and [Python SDK](reference/python-sdk.md).
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

- <a href="../../ru/latest/">Русская документация</a>
