# Nodrix 1.5.1

Nodrix 1.5.1 is a hardening release. It preserves the 1.5 graph and node APIs
while making configuration failures explicit, reducing the minimal Core
dependency surface and making network services safe by default.

## Highlights

- Unknown manifest fields and unsupported `apiVersion` values fail validation.
- Optional inputs are an explicit node contract and may be left unconnected.
- Core nodes load without importing Vision, Media or Recording providers.
- Lock checks cover dependencies and the compatible Python/runtime environment.
- Streams and generated metrics endpoints bind to loopback by default.
- Stream handshakes have time, size, concurrency and client limits.
- Tokens are supplied explicitly or by environment and are forbidden in URIs.
- Every run records `events.jsonl` and `resolved-plan.json`.
- Graceful shutdown deadlines also apply after finite sources finish.

Public Internet or LAN exposure remains an explicit production decision and
must be paired with access control. A strict production validation reports
unprotected non-loopback streams and metrics endpoints as errors.
