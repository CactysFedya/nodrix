# ADR-0004: Canonical foreground Operation execution

- **Status:** Accepted
- **Date:** 2026-08-19
- **Scope:** Nodrix 2.23

## Context

Nodrix has one canonical execution model:

`Operation -> PlanRecord -> ExecutionRecord -> RunRecord`.

Workflow, benchmark, optimization and extension-backed operations already
used these canonical records, but their outer services independently
connected execution to persistent Run history.

That duplication allowed operation domains to drift into different
lifecycle and persistence behavior even though their canonical records
were identical.

Nodrix also needs a clear foreground execution contract before adding any
future scheduling, remote execution or asynchronous control-plane
features.

## Decision

### One foreground persistence boundary

Nodrix defines `persist_foreground_execution()` as the common boundary
between an exact executed Plan and canonical Run persistence.

It receives:

- one exact `PlanRecord`;
- one `ExecutionRecord` produced from that exact Plan;
- optional canonical Run persistence inputs such as summary, metadata,
  materialized inputs/outputs and additional provenance.

It produces a service-level `ForegroundOperationResult` containing:

- the exact Plan;
- the exact ExecutionRecord;
- the resulting persisted canonical Run history.

`ForegroundOperationResult` is not a new canonical persistent entity.
Persistent history remains `RunRecord`.

### Exact Plan invariant

Foreground persistence requires:

`execution.plan is plan`.

A result created for another PlanRecord cannot be persisted through the
foreground boundary.

This preserves exact Plan identity rather than merely comparing
equivalent-looking Plan values.

### Terminal execution invariant

Foreground persistence accepts only terminal `ExecutionRecord` values.

A running, prepared or otherwise non-terminal execution cannot become a
completed foreground Operation result.

Canonical Run persistence therefore remains downstream of terminal
execution.

### Registered extension Operations

Registered extension Operations use the complete generic path:

`Operation
-> ExtensionDispatcher.plan()
-> PlanRecord
-> ExtensionDispatcher.execute()
-> ExecutionRecord
-> persist_foreground_execution()
-> RunRecord`.

Planning and execution remain explicit so the exact PlanRecord remains a
first-class boundary value.

### Built-in domain Operations

Workflow, benchmark and optimization retain their domain-specific
planners and executors.

They join the common foreground path after their executor returns an
`ExecutionRecord`.

This is intentional.

Domain-specific executor arguments such as benchmark output locations do
not belong in the generic `PlanExecutor.execute(plan)` extension
contract.

Therefore Nodrix does not force all built-in executors through
`ExtensionDispatcher`.

### Persistence ownership

Operation-domain services must not call `persist_execution()` directly.

Direct canonical execution-history persistence is owned by the common
foreground boundary.

The layering is:

`domain Operation service
-> foreground boundary
-> execution history
-> RunRecord`.

### CLI boundary

CLI commands call domain Operation services.

CLI code must not directly call:

- `persist_execution()`;
- `persist_foreground_execution()`;
- `execute_foreground_operation()`.

The CLI therefore remains presentation/control input rather than Run
persistence architecture.

### Foreground-only semantics

This ADR introduces no:

- background execution mode;
- detach mode;
- daemon Operation;
- Job entity;
- scheduler;
- remote queue;
- process supervisor contract.

A foreground Operation call returns only after its execution reaches a
terminal canonical state and Run persistence succeeds.

Future asynchronous execution may reuse the same canonical
Operation/Plan/Execution/Run model, but it requires a separate explicit
contract.

### Operation-kind independence

The foreground boundary does not depend on `OperationKind`.

Run, test, benchmark, profile, diagnostics and custom Operations do not
receive different fundamental Execution or Run types.

Domain-specific behavior belongs to planning and execution, not to
parallel lifecycle models.

### ExecutionPolicy

`ExecutionPolicy` remains a separate cross-domain Execution / Run policy
contract established by ADR-0003.

Foreground execution does not move policy into System Definition,
Plan identity or operation-specific result types.

## Consequences

- canonical Run persistence has one foreground ownership boundary;
- exact Plan identity is enforced before persistence;
- only terminal executions become persisted foreground results;
- built-in domains keep their specialized execution semantics;
- extension dispatcher remains free of persistence;
- CLI remains above domain Operation services;
- Operation kinds share one Execution and Run lifecycle;
- future asynchronous execution cannot be added as an implicit boolean
  switch to this contract.
