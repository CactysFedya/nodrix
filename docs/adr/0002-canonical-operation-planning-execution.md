# ADR-0002: Canonical Operation, planning, and execution contract

- **Status:** Accepted
- **Date:** 2026-08-19
- **Scope:** Nodrix 2.23

## Context

Nodrix supports different engineering actions such as run, build, test,
profile, benchmark, diagnostics, calibration, export, packaging, cleanup,
and user-defined operations.

These actions must not create separate execution architectures.

The canonical operational path is:

Operation -> OperationPlanner -> PlanRecord -> PlanExecutor
-> ExecutionRecord -> RunRecord

## Decision

### Operation

`Operation` represents intent only.

It contains:

- an extensible `OperationKind`;
- a canonical subject;
- an optional subject revision;
- operation-specific parameters.

Operation must not contain backend state, execution state, process handles,
timestamps, executor identity, or Run identity.

`OperationKind` is extensible rather than a closed Enum. Packages may use
namespaced kinds without modifying Nodrix Core.

### Planning

Revision resolution belongs to planning.

`Operation.subject_revision` may therefore be absent when the request is
created.

A resulting `PlanRecord` must always pin an immutable
`subject_revision`.

`OperationPlanner` consumes:

- one `Operation`;
- one explicit `PlanningContext`.

Planning policy must not be hidden inside execution.

A planner must not implicitly infer project roots, scan arbitrary storage,
reread execution configuration, or rely on mutable ambient state when that
information should be provided through resolved planning context.

### Plan

`PlanRecord` is the resolved execution authority for an operation.

It preserves:

- Plan identity;
- Plan kind;
- the originating Operation;
- exact resolved subject revision;
- domain-specific resolved payload;
- metadata.

Planning and execution are separate stages.

### Execution

`PlanExecutor.execute()` accepts a `PlanRecord` and returns an
`ExecutionRecord`.

An executor does not accept an Operation or Definition as an alternative
execution input.

`ExecutionRecord` references the exact Plan that was executed.

Operation and subject provenance are derived through that Plan rather than
copied into independent mutable fields.

### Run

All operation kinds share one canonical `ExecutionRecord` and one canonical
`RunRecord`.

Core must not create fundamental operation-specific types such as:

- `BenchmarkRunRecord`;
- `TestRunRecord`;
- `ProfileRunRecord`;
- `DiagnosticsRunRecord`.

Domain-specific results belong in typed records, metrics, artifacts,
relations, execution details, or aggregate results rather than in a second
Run hierarchy.

### Built-in and custom operations

Nodrix defines conventional operation kinds including:

- prepare;
- build;
- test;
- validate;
- run;
- profile;
- benchmark;
- optimize;
- diagnose;
- calibrate;
- export;
- package;
- cleanup.

These names are conventions, not a closed universe.

Packages may define operation kinds such as
`vendor.hardware-check` or `slam.evaluate`.

A custom operation still produces the same canonical Plan, Execution, and
Run model.

### Dispatcher

The canonical dispatcher keeps planning and execution explicit:

`dispatch(operation, context)` is equivalent to:

`plan(operation, context)` followed by `execute(plan)`.

The dispatcher verifies that:

- the planner returned a Plan for the requested Operation;
- the executor returned an Execution for the selected Plan;
- executor identity matches the selected executor.

### Benchmark and test semantics

Benchmark, test, profile, diagnostics, and similar domains may provide
their own planners, executors, metrics, artifacts, and aggregate results.

They do not receive separate Core execution or Run models.

In later Nodrix contracts, benchmark is modeled as ordinary Runs plus
structured aggregate comparison rather than as a separate runtime.

## Compatibility

Existing workflow, benchmark, optimization, and extension execution paths
already use the canonical Operation / Plan / Execution model.

Legacy Pipeline execution may remain behind compatibility boundaries during
the 2.x transition, but it must not redefine this canonical operational
contract.

## Validation evidence

Nodrix 2.23.1 adds architecture invariants covering:

- unresolved Operation intent;
- mandatory resolved Plan revision;
- Execution provenance through Plan;
- Run provenance through Execution;
- extensible Operation kinds;
- explicit PlanningContext;
- Plan-only executor input;
- planning/execution separation;
- absence of operation-specific Core Run types.

Operation architecture regression result:

124 passed.
