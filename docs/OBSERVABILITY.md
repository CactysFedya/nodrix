# Observability

Every run writes structured events, JSON metrics, status and summary artifacts.
Prometheus text is available through the configured metrics listener. Optional
OpenTelemetry lifecycle tracing is outside the message dataplane:

```yaml
runtime:
  tracing:
    enabled: true
    exporter: otlp
    endpoint: http://127.0.0.1:4317
    service_name: nodrix-camera
```

Install `nodrix[otel]` for console or OTLP exporters. Disabled tracing imports no
OpenTelemetry package and performs no per-message span work.

Correlation metadata is stable on local, process, network, and recording paths:

```text
pipeline_id · run_id · source_id · sequence · timestamp_ns · trace_id
```

Lifecycle events include pipeline start/stop, node readiness/failure/fallback,
stream readiness, selected backends, and explicit error reasons. Health
snapshots expose state, reason, transition timestamp, restart count, last error,
queue pressure, and readiness.
