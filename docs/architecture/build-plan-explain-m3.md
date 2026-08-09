# Build Plan / Explain M3

M3 makes the Build Recipe API inspectable before execution.

## Commands

```bash
plyctl build --plan
plyctl build --plan --json
plyctl build --explain fast-lio2
plyctl build --plan --rebuild
```

`--plan` is read-only: no build command is started and no workflow operation run directory is created.

## Example

```text
BUILD PLAN · build · generated recipes

#  STATUS   STEP          RECIPE         DEPENDS       CACHE  REASON
1  CACHED   livox-sdk2    cmake.release  -             hit    unchanged
2  CACHED   livox-driver ros2.colcon     livox-sdk2    hit    unchanged
3  PLANNED  fast-lio2    ros2.colcon     livox-driver  miss   cache fingerprint changed
```

A focused explanation is available with:

```bash
plyctl build --explain fast-lio2
```

It reports the recipe, dependencies, cache decision, tracked inputs/outputs,
tracked environment variables and the reason the step is cached, skipped or
scheduled.

## Dependency-safe cache

M3 also tightens execution semantics. If a declared dependency actually runs in
the current build, a dependent cached step is invalidated for that build. This
prevents a stale dependent from remaining `CACHED` after an upstream library or
ROS overlay was rebuilt.

The existing M1 cache format remains compatible; M3 does not wipe or migrate
cache state.

## Scope

M3 intentionally does not add new recipes. It improves observability and cache
correctness for the M2 recipes and for advanced raw workflows using
`depends_on`.
