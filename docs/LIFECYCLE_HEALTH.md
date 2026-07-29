# Lifecycle, health and watchdog

```yaml
nodes:
  model:
    execution:
      isolation: process
    failure:
      policy: restart
      max_restarts: 3
      backoff_ms: 250
    health:
      timeout_ms: 2000
      on_timeout: restart
```

```bash
nodrix status
nodrix health --watch
```

A watchdog restart terminates the hung child and lets the owning worker serialize recovery. The graph does not concurrently manipulate the same IPC connection. In-process Python code cannot be force-killed safely; strict validation recommends process isolation.
