# Stable Manifest v2

Manifest v2 is the stable pipeline contract for Nodrix 2.x:

```yaml
apiVersion: nodrix.dev/v2
kind: Pipeline
metadata:
  name: example
runtime:
  engine: unified
nodes:
  source:
    uses: core.synthetic_source
    health:
      timeout_ms: 5000
fragments: {}
edges: []
streams: {}
recording: {}
security: {}
placement: {}
```

All nine sections shown above are explicit and required. Unknown fields are
rejected. `runtime.engine` must be `unified` or `native`; v2 does not make an
implicit executor choice.

## Compatibility

- Nodrix 2.x continues to read `nodrix.dev/v1` pipelines.
- Newly generated projects use v2.
- The v2 field meanings and public port contracts are stable within 2.x.
- A future breaking schema uses a new `apiVersion`; it is not silently
  reinterpreted.

Use `nodrix migrate pipeline.yaml --to v2` to create `pipeline.v2.yaml`.
The source is untouched unless `--in-place` is requested.

## Stable policies

Failure policies are `stop_pipeline`, `restart_node`, `fallback_node`,
`isolate_branch`, and `skip_message`. The legacy `restart` and
`disable_branch` names remain readable in v1.

Every edge has a bounded queue. Memory domains and copy permission are explicit:

```yaml
edges:
  - from: source.output
    to: detector.input
    queue: {capacity: 2, policy: latest}
    memory: {domain: auto, allow_copy: true}
```

Run `nodrix validate pipeline.yaml --production`, `nodrix inspect --memory`, and
`nodrix plan pipeline.yaml` before deployment.
