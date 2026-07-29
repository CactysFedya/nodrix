# Runtime Profiles

Profiles provide task-specific defaults without changing the data plane.

| Profile | Purpose | Default queue |
|---|---|---|
| `realtime-low-latency` | live cameras, inference, Viewer | `latest:1` |
| `realtime-balanced` | general realtime graphs | `drop_oldest:2` |
| `lossless-recording` | recording and reproducible capture | `block:32` |
| `maximum-throughput` | offline processing and benchmarks | `block:64` |
| `debug` | dense telemetry and full type validation | `block:8` |

Resolution order:

```text
schema defaults
→ selected profile
→ pipeline.yaml
→ CLI --profile / --set
```

A specific node or edge always overrides the profile.

```yaml
profile: realtime-low-latency

flow:
  - source.frame -> encoder.frame
  - from: encoder.encoded
    to: recorder.frame
    queue:
      capacity: 32
      policy: block
```

List profiles:

```bash
nodrix config profiles
```
