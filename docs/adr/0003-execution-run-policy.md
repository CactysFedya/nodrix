# ADR-0003: Execution and Run policy

- **Status:** Accepted
- **Date:** 2026-08-19
- **Scope:** Nodrix 2.23

## Context

Nodrix uses one canonical Execution and Run model for run, test,
benchmark, profile, diagnostics and custom operations.

Cross-domain control-plane settings must therefore not be duplicated
into operation-specific Run types or embedded into architectural
System Definitions.

At the same time, reproducible Run history must record the effective
policy used around an exact execution.

## Decision

### ExecutionPolicy

Nodrix defines one immutable `ExecutionPolicy` shared by all operation
kinds.

The initial policy contains:

- `RunEnvironmentPolicy`;
- `RunLogPolicy`.

This is a cross-domain control-plane policy.

It does not alter the semantic contents of the exact `PlanRecord`.

### Ownership

ExecutionPolicy belongs to Execution / Run policy.

It does not belong to `SystemModel` or another architectural
Definition.

Therefore one exact System and Plan may be executed multiple times with
different control-plane policies without changing Definition identity
or Plan identity.

### Semantic execution settings

Settings that change what is actually executed must remain part of
planning and the exact Plan.

Examples include:

- topology;
- placement;
- dependency semantics;
- queue behavior;
- restart semantics;
- execution-affecting resource constraints.

They must not be silently hidden in ExecutionPolicy.

### Lifecycle Events

Critical lifecycle Events are mandatory historical evidence.

ExecutionPolicy therefore does not contain an `events_enabled` switch.

### Logs

Detailed diagnostic Logs remain optional and bounded.

`RunLogPolicy` controls:

- enabled/disabled state;
- minimum level;
- categories;
- total byte limit;
- per-category byte limit;
- per-record byte limit;
- overflow behavior;
- redaction.

Logs remain distinct from Events, Metrics and Artifacts.

### Environment provenance

Runtime environment capture is allowlist-only.

Process environment variables are not captured implicitly.

The effective allowlist and redaction configuration are part of Run
policy provenance.

### Secret material

Literal values configured in `RedactionPolicy.secrets` are never written
to `policy.json`.

Instead policy provenance records only:

- whether literal secrets were configured;
- how many were configured;
- that their values were intentionally not persisted.

### Persistent provenance

Persistent Runs using `nodrix.run-layout/v2` contain immutable
`policy.json`.

Publication order is:

`RunSession -> Definition snapshot -> Plan snapshot -> policy.json
-> environment.json -> backend preparation`.

Failure to publish policy provenance prevents backend preparation.

The Run directory remains as evidence of the failed execution attempt.

### Plan identity

ExecutionPolicy is deliberately not included in `PlanRecord.plan_id`.

Two Runs may therefore have:

- the same Definition;
- the same exact Plan;
- the same Plan ID;
- different ExecutionPolicy provenance.

This distinction is required for future structured Run comparison.

### Compatibility

`nodrix.run-layout/v1` remains supported as immutable historical
compatibility.

Layout v1 does not require `policy.json`.

New persistent Runs use `nodrix.run-layout/v2`.

For layout v2:

- missing `policy.json` is incomplete provenance (`REC107`);
- malformed or identity-inconsistent `policy.json` is corruption
  (`REC410`).

Existing `environment_policy=` and `log_policy=` runtime arguments are
retained temporarily as a compatibility surface.

They are deterministically converted into one effective
`ExecutionPolicy`.

Supplying the new `execution_policy=` argument together with legacy
policy arguments is rejected rather than merged implicitly.

## Deferred work

Typed Metrics are a separate entity and are introduced separately.

Observability profiles such as minimal, standard, debug and benchmark
are also defined separately.

No YAML authoring syntax is introduced by this ADR. Creating an
undocumented YAML representation here would violate Nodrix schema and
self-description rules; the authoring/schema binding is deferred until
the observability-profile contract is introduced.

## Consequences

- all operation kinds share one execution-policy model;
- System Definitions remain architectural rather than operational;
- Plan identity remains semantic;
- Run provenance records the actual effective control-plane policy;
- historical v1 Runs remain readable;
- future `runs compare` can distinguish policy differences without
  inventing operation-specific Run types.
