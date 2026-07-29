# Nodrix 1.0.0 — Production Runtime

Nodrix 1.0 freezes the main SDK and plugin contracts and adds the operational layer required to run typed streaming graphs reproducibly and safely.

## Compatibility promise

During the 1.x line, patch and minor releases preserve the documented Python API and Plugin ABI 1.0. Breaking API or ABI changes require Nodrix 2.0. Experimental hardware backends can evolve behind the stable buffer and memory interfaces.

## Production additions

1. Lifecycle, readiness, health, watchdog and controlled failure policies.
2. Checksummed `.ndpkg` packages with local installation only.
3. Deterministic lock files covering manifests, local nodes, native libraries, models, configs, schemas and installed package files.
4. Schema versions embedded in every wire message.
5. Token/IP stream access controls and parser size limits.
6. Strict graph validation and memory-copy diagnostics.
7. Run artifacts, metrics JSONL, Prometheus export and run comparison.
8. Stable C++ ABI 1.0 with pre-load inspection.
9. Secret redaction in resolved manifests and runtime artifacts.
10. Secure project templates: localhost by default, explicit token-protected network template.

## Upgrade from 0.9

Python nodes remain compatible. C++ plugins must be rebuilt because the experimental ABI 3 was promoted to official ABI 1.0 (`0x00010000`). Existing pipeline manifests remain valid; strict validation can now report open network exports and unsafe watchdog/resource combinations.

## Verification summary

- **59** Python unit/integration tests passed.
- Native Release and ASan/UBSan CTests passed **1/1**.
- Mixed Python/C++ graph processed **60 frames**.
- Wire fuzz: **5000** malformed inputs rejected without a crash.
- Stream reconnect stress: **200/200**.
- Runtime repetition: **50 × 1000 messages**.
- Wheel and source distribution were installed and executed outside the source tree.

A true 24-hour hardware soak test was not performed; see `VERIFICATION.md` for exact scope and environment limitations.
