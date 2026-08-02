# Nodrix 2.2.0-alpha.3 — Modular Integration Sessions

This alpha removes the main coupling and repeated-work problems found in the
ROS 2 orchestrator while keeping existing Nodrix YAML valid.

## Architecture

- Provider API 2 adds pipeline-scoped sessions and external-link descriptors;
- the contracts are integration-neutral and can be reused by ROS 2, Zenoh,
  MQTT, Kafka, database, or remote-service providers;
- Provider API 1 and manifests without `sessions` or `links` remain supported;
- provider capability negotiation now sees capabilities supplied by other
  installed providers without importing them;
- provider-owned templates work through the normal `nodrix init --template`
  command.

## ROS 2 package split

```text
nodrix
├── nodrix-spatial          transport-neutral spatial contracts
├── nodrix-mapping          mapping contracts and alpha aliases
├── nodrix-ros2 0.3.1       ROS platform/session/orchestration
└── nodrix-spatial-ros2     optional typed ROS ↔ Spatial bridges
```

`nodrix-ros2` no longer has a hard dependency on `nodrix-spatial`. Existing
adapter imports remain compatibility shims, while new deployments install the
bridge package explicitly.

## Runtime and performance

- one ROS workspace preparation and sourced environment per pipeline session;
- one lazy persistent ROS graph worker instead of repeated `ros2 topic list`
  subprocess polling;
- graph-only PointCloud2 readiness checks avoid a payload subscription;
- external `ros2.topic` links keep ROS-to-ROS data in DDS and create no Nodrix
  queues or planned copies;
- workspace fingerprints include underlays, build command, toolchain, Python,
  environment, and source identity;
- an inter-process workspace lock prevents concurrent builds;
- colcon build timeout/cancellation uses the managed process supervisor;
- per-process log rotation and command hashes improve bounded diagnostics;
- sourced Python environments are restored when the session closes;
- startup failures now trigger best-effort cleanup of sessions, processes,
  streams, recording, metrics, and tracing.

## YAML and project generation

Old `nodes + edges` files remain valid. ROS graphs add one `sessions` section,
normal node `bindings`, and optional logical `links`. Generate a maintained
example with:

```bash
nodrix init my-robot --template ros2
```

The Livox → FAST-LIVO2 → RViz integration was migrated to this shape.

## Validation scope

Offline unit tests cover Provider APIs 1/2, old and new manifest shapes,
parameter schemas, teardown races, strict QoS, graph/sample monitoring,
logical-link compilation, restart/log supervision, workspace trust and
environment policy, spatial adapters, and provider metadata. CI also contains
a real ROS 2 Jazzy publisher/subscriber smoke job. Livox Mid-360S, FAST-LIVO2,
RViz rendering, and RMW performance validation remain required on the target
Ubuntu 24.04 robot system.
