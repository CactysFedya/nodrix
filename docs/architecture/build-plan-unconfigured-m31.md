# Build Plan M3.1 — unconfigured project UX

M3.1 does not change the Build Recipe API, workflow planner, cache format, or
execution semantics.

It only makes `plyctl build`, `plyctl build --plan`, and
`plyctl build --explain STEP` fail clearly when the active project has no build
definition.

A project has build configuration when either:

- `nodrix.yaml` declares the high-level `build:` recipe mapping; or
- the project registers a legacy/advanced `workflows.build` workflow.

Before M3.1 an unconfigured project fell through to the workflow loader and
reported a low-level error such as:

```text
workflows entry 'build' was not found at .../workflows/build.yaml
```

After M3.1:

```text
Build is not configured for this project.
Add a build: section to nodrix.yaml or register workflows.build.
Available recipes: plyctl project recipes
```

`--json` returns a machine-readable `not_configured` status.

The command exits with status 1 so missing build configuration cannot be
mistaken for a successful empty build.
