# Metrics and run artifacts

```bash
nodrix run --metrics-listen 127.0.0.1:9464
nodrix metrics --format prometheus
nodrix runs list
nodrix runs compare RUN_A RUN_B
```

Metrics include node message/error/restart counts, processing and end-to-end latency, queue depth/drops, bytes, stream subscribers/traffic, readiness and health. `metrics.jsonl` preserves time-series snapshots; `status.json` is atomically replaced for low-cost live inspection.
