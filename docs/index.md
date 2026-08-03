# Plyctl documentation

Plyctl is a Pipeline OS for real-time local and distributed systems. It runs
Python and C++ nodes, ROS 2 applications, external processes, devices, and
transports as one typed and observable graph.

The documentation follows the same top-level organization used by ROS 2:
installation and first steps, tutorials, task-oriented guides, concepts, and
reference material.

```{toctree}
:maxdepth: 2
:caption: Documentation

getting-started/index
tutorials/index
how-to-guides/index
concepts/index
reference/index
integrations/index
contributing
release-notes
```

## Current release

This site documents **Plyctl 2.2.0 alpha.5**. Only the current release notes are
published here. The complete history remains available in `CHANGELOG.md` and
GitHub Releases.

## Compatibility promise

Plyctl 2.x accepts both `plyctl.dev/v1`/`v2` and the previous
`nodrix.dev/v1`/`v2` manifest values. The `nodrix` Python import and CLI alias
remain available throughout 2.x. Native ABI names, `.ndrx` recordings,
`nodrix://` URIs, and current provider IDs remain unchanged until a separately
versioned major migration.
