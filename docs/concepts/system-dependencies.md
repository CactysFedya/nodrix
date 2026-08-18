# System dependencies and readiness

Nodrix 2.20 lets a parent System declare startup dependencies between its
direct child System instances. The contract is backend-neutral: it does not
refer to ROS 2 topics, processes, services, or particular hardware.

## Authoring contract

```yaml
apiVersion: nodrix.system/v1
kind: System
name: mapping

systems:
  - name: sensor              # Sibling instance name in this parent.
    uses: ./livox.yaml        # Path or pinned Definition revision.
  - name: localization
    uses: ./fast-livo2.yaml
  - name: mapping
    uses: ./mapping.yaml

dependencies:
  - system: localization      # Start this child after the condition succeeds.
    requires: sensor          # Direct sibling prerequisite.
    condition: ready          # started | ready | healthy
    timeoutSeconds: 30        # Finite per-edge monotonic deadline.
  - system: mapping
    requires: localization
    condition: healthy
    timeoutSeconds: 60
```

`system` and `requires` can name only direct siblings. Self-dependencies,
missing siblings, duplicate edges, and cycles are rejected before execution.
Dependencies do not cross a parent boundary and do not flatten child plans.

## Conditions

- `started`: the prerequisite returned a live System execution handle;
- `ready`: its aggregated `ExecutionObservation.ready` is `true`;
- `healthy`: its aggregated health is `healthy`.

Each satisfied condition becomes a startup latch. A later observation change
does not undo a startup decision. Continuous failure propagation and restart
policy belong to the production lifecycle contract.

An unavailable observation is not treated as success. `failed`, `unhealthy`,
or a terminal state reached before the requested condition fails immediately.
Temporary `not ready`, `unknown`, or `degraded` observations wait until the
edge deadline.

## Planning and execution

The planner validates the dependency graph once and writes
`system_startup.dependencies`, `system_startup.order`, and
`system_startup.roots` into the `SystemExecutionPlan`. Runtime consumes that
compiled topology; it does not rebuild the DAG.

Independent roots start without waiting for unrelated branches. Observation
polling is bounded and uses a monotonic clock. On any startup failure, already
started child Systems stop in reverse actual start order, followed by the
parent's direct scopes.

Systems without `dependencies` keep their pre-2.20 declaration-order behavior
and plan identity.

## Observation and automation

Human output from `plyctl system run` reports `CHILD STARTED`,
`DEPENDENCY WAITING`, `DEPENDENCY SATISFIED`, and `DEPENDENCY FAILED` while
startup is in progress.

`--output jsonl` exposes the corresponding versioned events:

```text
child_started
dependency_waiting
dependency_satisfied
dependency_failed
```

Dependency events include the parent execution ID, child and prerequisite
names, condition, timeout, elapsed time, and failure message when applicable.

## Python SDK

```python
from nodrix import SystemDependency, SystemDependencyCondition

dependency = SystemDependency(
    system="mapping",
    requires="localization",
    condition=SystemDependencyCondition.HEALTHY,
    timeoutSeconds=60,
)
```

Stable diagnostics used by this contract include `SYS061`–`SYS064` for model
references, `PLAN406` for cycles, and `ORCH301`–`ORCH305` for timeout,
prerequisite failure, unhealthy state, unavailable observation, and an invalid
compiled startup plan.
