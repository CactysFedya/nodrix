# Process Isolation

Use the normal `Node` API and configure placement in YAML:

```yaml
nodes:
  detector:
    uses: ./nodes/detector.py:Detector
    execution:
      isolation: process
      cpu_affinity: [2, 3]
    failure:
      policy: restart
      max_restarts: 3
      backoff_ms: 100
```

Use isolation for expensive, unstable, or independently restartable nodes.
Keep tiny adapters in-process. Policies in 0.8.0 are `stop_pipeline`, `restart`,
and `skip_message`. Process-isolated sources are intentionally unsupported in
this release.
