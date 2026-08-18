# Nodrix roadmap: 2.19 to 3.0

Nodrix is moving to a description-driven executable architecture:

```text
Description → SystemModel → ExecutionPlan → Backend → Runtime → Run Record
```

Definitions are versioned and reproducible. A nested System remains an
independent component. The planner performs topology work once; runtime
consumes the compiled plan. Declarative YAML never stores live execution
state. Core contracts remain independent from ROS 2, Dora, CV frameworks, and
specific hardware.

Every milestone requires targeted tests, the full test suite before its local
commit, stable structured diagnostics, synchronized English/Russian
documentation, and self-describing generated YAML. Only proven dead or
duplicate code is removed.

## Completed baseline

- **2.19 — hierarchical System composition:** pinned child Definitions,
  recursive planning, lifecycle and rollback, observation, human status, and
  versioned JSONL events.

## Implementation sequence

- **2.20 — dependencies and readiness:** sibling `SystemDependency`,
  `started`/`ready`/`healthy`, per-edge deadlines, cycle detection, compiled
  deterministic DAG, independent startup branches, bounded polling, failure
  propagation, reverse-actual-order rollback, and observable startup events.
- **2.21 — complete System interfaces:** inputs and outputs, parent-to-child
  and sibling bindings, parameter/context/resource passing, required and
  optional ports, type/direction validation, local links, and explicit
  transport boundaries without hidden flattening.
- **2.22 — canonical System Run:** versioned run directory containing source
  and resolved Systems, exact plan/context, event journal, atomic live/final
  status, environment provenance, redaction, logs, and recovery metadata.
- **2.23 — operational CLI:** run history, status, inspect, logs, stop,
  restart, attach, detach/follow modes, stable output formats and exit codes,
  and safe idempotent control by Run ID.
- **2.24 — production lifecycle and LocalBackend:** process-group ownership,
  signal handling, graceful/forced shutdown, orphan prevention, stale-run
  recovery, restart policies and backoff, subsystem restart, isolation and
  supported resource limits, failure injection, and endurance tests.
- **2.25 — packaging and portability:** wheel/sdist and clean-install tests,
  reproducible/offline dependency sets, macOS/Linux and Python 3.12/3.13,
  aarch64 preparation, doctor/preflight checks, provider and ROS 2 environment
  diagnostics, and installation upgrade/rollback.
- **2.26 — compatibility and migration:** freeze the Pipeline/System boundary,
  preserve real legacy projects through explicit adapters, automated migration
  with semantic-loss reports, deprecation registry, schema upgrades and hash
  rules, and removal of proven dead/duplicate legacy paths.
- **2.27 — security, trust, and provenance:** secret redaction, environment
  isolation, path/symlink/archive protections, checksums and pinned artifacts,
  provider/resource trust policy, secure Run permissions/retention/recovery,
  and Definition → Plan → Run → Artifact provenance.
- **2.28 — documentation and reference project:** complete EN/RU architecture,
  SDK, lifecycle, Run, CLI, migration, troubleshooting, security, offline, and
  Raspberry Pi guides; simulated `rpi5-mapping` composed from Livox,
  FAST-LIVO2 LIO-only, mapping, monitoring, and recording Systems.
- **2.29 — stabilization and API freeze:** freeze System, Backend, Run, and
  Event contracts; public-import and schema snapshots; wheel install; full
  regressions and failure injection; hardware-free soak, performance and leak
  baselines; clean documentation build; release and migration notes.

## 3.0 release boundary

The local completion target is **3.0.0rc1**, with no known P0/P1 defects. Final
**3.0.0** is released only after Raspberry Pi qualification of clean install,
doctor/planner, simulated and real Livox/FAST-LIVO2/mapping Systems, readiness
failure scenarios, restart/recovery, graceful shutdown, detached operation,
Run records, hardware soak, performance, memory, CPU, and temperature.

Remote agents, secure cross-host management, package delivery, cross-host
transport, reconnect, and network-partition behavior remain post-3.0 work.
