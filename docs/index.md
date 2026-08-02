# Plyctl documentation

Plyctl is the Pipeline OS for real-time systems. One typed YAML graph can
supervise Python and C++ nodes, ROS 2 applications, external processes,
devices, and transports without coupling the core runtime to one ecosystem.

```{toctree}
:maxdepth: 2
:caption: Start here

getting-started/index
concepts/pipeline-os
```

```{toctree}
:maxdepth: 2
:caption: Use Plyctl

reference/cli
integrations/ros2
```

```{toctree}
:maxdepth: 2
:caption: Project

migration/nodrix-to-plyctl
releases/index
```

```{toctree}
:maxdepth: 1
:caption: Complete 2.x reference library
:hidden:
:glob:

[A-Z]*
```

## Stable compatibility promise

Plyctl 2.x accepts both `plyctl.dev/v1`/`v2` and the previous
`nodrix.dev/v1`/`v2` manifest values. The `nodrix` Python import and CLI alias
also remain available. Native ABI names, `.ndrx` recordings, `nodrix://` URIs,
and current provider IDs remain unchanged until a separately versioned major
migration.
