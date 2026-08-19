# Architecture decision records

Architecture decisions protect the product principles from accidental drift.
Use an ADR for changes to product identity, Core boundaries, schemas,
compatibility, security, lifecycle ownership, transports, or artifact formats.

Each ADR records:

- status and date;
- context and constraints;
- considered options;
- decision;
- compatibility and migration effects;
- performance and security effects;
- validation evidence.

A feature-specific implementation detail does not need an ADR unless it changes
a public or architectural contract.

## Accepted decisions

- [ADR-0001: Run lifecycle, persistence, and recovery](0001-run-lifecycle-persistence-recovery.md)
- [ADR-0002: Canonical Operation, planning, and execution contract](0002-canonical-operation-planning-execution.md)
- [ADR-0003: Execution and Run policy](0003-execution-run-policy.md)
