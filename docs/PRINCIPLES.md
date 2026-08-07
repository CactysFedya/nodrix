# Plyctl product principles

These principles are normative for the 2.x line. A feature is not accepted
merely because it works in one integration; it must preserve the generic
runtime and operations model.

## 1. Core stays universal

Core models projects, finite workflows, runtime graphs, nodes, applications,
resources, contracts, health, metrics, and artifacts. It does not contain
Livox-, FAST-LIVO2-, YOLO-, camera-, or robot-specific behavior. Ecosystem
logic belongs in providers, recipes, project-owned packages, native plugins,
and qualified examples.

## 2. Control plane and data plane remain separate

Plyctl supervises lifecycle, readiness, health, dependencies, logs,
provenance, and shutdown. High-volume data follows the most appropriate
transport: in-process memory, shared memory, a native plugin, ROS 2 DDS,
FFmpeg, or device memory. Core must not deserialize images or point clouds
simply to observe a pipeline.

## 3. Explicit operations, no hidden installation

`plyctl run` executes a prepared pipeline. It must not silently call `sudo`,
install system packages, update repositories, or rebuild unrelated sources.
Setup, source resolution, patching, building, and verification are finite,
explicit operations with inspectable plans and logs.

## 4. Reproducibility before convenience

Sources are pinned, patches are verified, models and calibration artifacts have
identities, and every run records resolved configuration and environment
evidence. Automation may be simple to invoke, but it must never become
untraceable magic.

## 5. Progressive project structure

A project starts with `nodrix.yaml`. Directories such as `pipelines/`,
`workflows/`, `packages/`, `calibration/`, and `patches/` appear only when the
project needs them. Templates are conventions, not a domain-specific
filesystem imposed by Core.

## 6. Typed contracts at boundaries

Ports, external edges, artifacts, and provider capabilities use explicit,
versioned contracts. `core.any` is acceptable for exploration, not for a
qualified production boundary.

## 7. Performance is observable

Latency, queue age, drops, copies, throughput, CPU, RSS, child processes,
temperature, and fallback decisions must be measurable. Performance claims
require evidence and regression budgets.

## 8. Safe lifecycle ownership

Plyctl owns only the processes it starts. It uses process groups and tracked
identities, attempts graceful shutdown first, and never relies on broad
`pkill -f` patterns.

## 9. Offline and edge operation are first-class

Provider wheels, source locks, patches, checksums, models, and documentation
can be bundled and verified without a mandatory cloud service or central
scheduler.

## 10. Compatibility changes are deliberate

The 2.x compatibility names remain supported according to the compatibility
policy. A breaking schema, ABI, provider, CLI, or artifact change requires a
migration path and an explicit decision record.

## Applying the principles

Reviews should ask:

1. Does this add domain behavior to Core?
2. Does it create an unnecessary data copy or Python bottleneck?
3. Can the result be reproduced on another machine?
4. Can the operator explain what happened from logs and artifacts?
5. Does shutdown affect only owned processes?
6. Is the public promise supported by tests and evidence?
