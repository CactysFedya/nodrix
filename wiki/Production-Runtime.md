# Production Runtime

Nodrix 1.0 adds stable lifecycle states, health snapshots, watchdog recovery for isolated nodes, graceful shutdown, resource limits, failure policies, status/metrics commands and complete run artifacts.

```bash
nodrix validate --strict
nodrix lock
nodrix run --locked --metrics-listen 127.0.0.1:9464
nodrix health --watch
```
