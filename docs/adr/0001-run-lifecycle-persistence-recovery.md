# ADR-0001: Run lifecycle, persistence, and recovery

- **Status:** Accepted
- **Date:** 2026-08-19
- **Scope:** Nodrix 2.22

## Context

Nodrix uses one canonical execution path:

Description -> SystemModel / Definition -> ExecutionPlan -> Backend -> Runtime -> Run

Version 2.22 establishes Run as a persistent, self-describing execution record.
The design must preserve exact provenance without turning high-volume runtime
data into expensive control-plane history.

## Decision

### Execution authority

`ExecutionPlan` is the only execution input of the runtime.

`SystemModel` may be supplied when starting a persistent Run only as Definition
provenance. Runtime must not reread YAML, recompute topology, or replan from the
Definition.

The canonical provenance relationship is:

Definition -> Plan -> Execution -> Run

### Persistent Run layout

A persistent Run session is created before backend preparation.

The Run directory contains lifecycle-dependent files:

- `session.json` — immutable Run session identity and exact Plan identity.
- `definition.json` — immutable canonical Definition provenance.
- `plan.json` — immutable exact resolved Plan snapshot.
- `environment.json` — immutable minimal environment provenance.
- `events.jsonl` — append-only lifecycle/control-plane history.
- `status.json` — atomically replaced mutable operational cache.
- `logs/` — optional bounded diagnostics.
- `run.json` — immutable terminal Run record.

Not every file is required to exist at every lifecycle stage.

### Provenance

Mandatory pre-execution provenance must be persisted before backend execution
starts. Failure to persist mandatory provenance blocks persistent execution.

Environment capture is minimal by default. Process environment variables are
included only through an explicit allowlist and pass through redaction.

The default contract never stores the complete `os.environ`.

### Events

`events.jsonl` is append-only historical evidence.

Events represent lifecycle and control-plane facts. They do not automatically
contain application messages or high-volume data-plane payloads.

ROS 2 topics, point clouds, images, sensor streams, and similar traffic remain
in their native data plane unless explicitly recorded as another artifact.

### Status

`status.json` is a mutable cache for efficient operational reads.

It is not canonical history and it is not a heartbeat.

`updatedAt` records the latest persisted status change. Its age alone must not
be used to classify a Run as interrupted.

Status is reconstructible from durable Run history.

### Logs

Logs are optional bounded diagnostics and are distinct from:

- Events;
- Metrics;
- Artifacts;
- data-plane payloads.

Optional log persistence failures do not control execution.

This best-effort rule does not apply to mandatory provenance.

### Final Run record

`run.json` is immutable and is published only after a terminal
`ExecutionRecord` exists.

Readers reject corrupted identity, invalid terminal semantics, non-standard JSON
numbers, timestamps without timezone information, and execution intervals where
`finishedAt` precedes `startedAt`.

A failure before execution starts may legitimately leave no `run.json`.

## Recovery semantics

Recovery is read-only interpretation of durable Run state.

Recovery does not restart execution, reattach to processes, assume process
ownership, act as a supervisor, or rewrite historical evidence.

A persisted non-terminal Run is `active-or-unknown` by default.

It becomes `interrupted` only when an external owner-aware context explicitly
knows that no live execution owner exists.

The age of `status.updatedAt` is not sufficient evidence.

## Performance and security

Run persistence is designed to remain inexpensive on low-resource hosts:

- lifecycle events are small control-plane records;
- status is one replaceable cache;
- logging is disabled by default and bounded when enabled;
- environment capture uses an allowlist;
- high-volume traffic remains outside canonical Run history.

Secret exposure is reduced through allowlisted environment capture and
redaction.

Mandatory historical provenance fails closed. Optional diagnostics fail open
with respect to execution availability.

## Compatibility

This ADR defines the Run contract being established for the Nodrix 3.0
architecture.

Legacy Pipeline execution may remain temporarily behind compatibility
boundaries during the 2.x transition, but canonical Run persistence must not
depend on legacy manifest semantics.

Future detached execution or supervision requires an explicit ownership and
liveness contract; it must not silently reinterpret `status.updatedAt` as a
heartbeat.

Metrics and Artifacts remain separate contracts.

## Validation evidence

Nodrix 2.22 tests cover Run creation, events, status, immutable final records,
Definition and Plan snapshots, environment redaction, bounded logs, real Run
recovery, strict JSON, timestamp validation, chronology, and provenance
consistency.

Acceptance regression:

1510 passed, 3 skipped, 7 known pre-existing warnings.
