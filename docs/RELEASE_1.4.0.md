# Nodrix 1.4.0 — Benchmark and Reproducibility

Nodrix 1.4.0 turns runtime telemetry and run artifacts into a repeatable benchmark workflow.

## Added

- `nodrix.benchmark/v1` benchmark specification;
- named variants with profile, `--set`, and block replacement values;
- separate warm-up and measured run artifacts;
- P50/P95/P99 aggregation for duration and node metrics;
- source/sink rate, end-to-end latency, drops, errors, memory, and temperature summaries;
- benchmark suite artifacts under `.nodrix/benchmarks/`;
- filtered environment snapshots and local model SHA-256 inventory;
- richer `runs compare` metrics while preserving old delta fields;
- `nodrix replay` eligibility checks and `.ndrx` replay execution;
- a benchmark specification for the Production Vision example.

## Compatibility

Nodrix 1.4.0 preserves the 1.x Node API, manifests, reusable blocks, typed messages, wire protocol, Plugin ABI 1.0, native runner plan, and `.ndrx` format.

## Release gates

- full Python test matrix 3.11–3.14;
- native C++ tests and native end-to-end test;
- benchmark unit tests with deterministic fake reports;
- sdist/wheel build and `twine check`;
- Raspberry Pi 5 reference benchmark for the 1.3 Vision pipeline;
- at least two repeated benchmark variants with complete suite artifacts.
