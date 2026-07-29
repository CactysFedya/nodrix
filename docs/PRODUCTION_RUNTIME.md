# Production Runtime

## Lifecycle

Nodrix 1.0 wraps legacy `open/flush/close` through the stable lifecycle API:

```text
configure → start → process/produce → drain → stop
```

The executor tracks state, health, readiness, last start/completion timestamps, errors, restarts and queue pressure.

## Failure policies

- `stop_pipeline`: fail the graph.
- `restart`: restart a process-isolated node.
- `skip_message`: drop the failed input and continue.
- `disable_branch`: close only the failed branch with EOS.

## Graceful shutdown

Sources stop first, edge queues unblock or drain, nodes flush, encoders and `.ndrx` indexes close, then buffers and process resources are released. `runtime.shutdown.timeout_ms` bounds shutdown after an interruption.

## Resource controls

Process isolation can apply CPU affinity and POSIX address-space/CPU limits. Message size and metadata limits protect the runtime from uncontrolled allocations. `validate --strict` warns where limits cannot be enforced safely in-process.
