# Production Runtime

## Lifecycle

Nodrix 2.0 wraps legacy `open/flush/close` through the stable lifecycle API:

```text
CREATED → CONFIGURING → READY → STARTING → RUNNING → STOPPING → STOPPED
                                            ├→ DEGRADED / RESTARTING
                                            └→ FAILED
```

The executor tracks state, reason, transition timestamp, health, readiness,
last message/completion timestamps, errors, bounded restarts and queue pressure.

## Failure policies

- `stop_pipeline`: fail the graph.
- `restart_node`: restart a process-isolated node up to `max_restarts`.
- `fallback_node`: replace an in-process processor/sink with an explicitly
  configured contract-compatible implementation.
- `skip_message`: drop the failed input and continue.
- `isolate_branch`: close only the failed branch with EOS.

## Graceful shutdown

Sources stop first, edge queues unblock or drain, nodes flush, encoders and `.ndrx` indexes close, then buffers and process resources are released. `runtime.shutdown.timeout_ms` bounds shutdown after an interruption.

## Resource controls

Process isolation can apply CPU affinity and POSIX address-space/CPU limits. Message size and metadata limits protect the runtime from uncontrolled allocations. `validate --strict` warns where limits cannot be enforced safely in-process.

## Deployment gate

```bash
nodrix run pipeline.yaml --production
```

Production mode requires Manifest v2, explicit engine and node health timeout,
and fails before execution on unsafe stream exposure, allowed software fallback,
planned copies, relative model paths, schema incompatibility, or missing plugin
verification. `runtime.logging.level: debug` is also rejected.
