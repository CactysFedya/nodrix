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

Provider API 2 integrations may add optional `sessions`, `resources`, and
`applications` without changing the meaning of the nine stable sections. A
physical/external Transport is attached to the logical Edge:

```yaml
sessions:
  bus:
    uses: example.session
    parameters: {}
applications:
  source:
    uses: example.publisher
    bindings: {session: bus}
  sink:
    uses: example.subscriber
    bindings: {session: bus}
nodes: {}
edges:
  - from: source.events
    to: sink.events
    transport:
      uses: example.topic
      parameters: {topic: /events}
```

Bindings require `runtime.engine: unified`; bound Nodes remain in-process.
Managed Applications are supervised outside the Nodrix data plane. An Edge
with `transport` does not allocate a local Nodrix queue or transfer its payload
through Core.

## Compatibility

- Nodrix 2.x continues to read `nodrix.dev/v1` pipelines.
- The `use` field and top-level `links` remain 2.x compatibility aliases.
  New files use `uses` and `edges[].transport`; strict validation rejects the
  deprecated spellings before production.
- Newly generated projects use v2.
- The v2 field meanings and public port contracts are stable within 2.x.
- A future breaking schema uses a new `apiVersion`; it is not silently
  reinterpreted.

Use `nodrix migrate pipeline.yaml --to v2` to create `pipeline.v2.yaml`.
The source is untouched unless `--in-place` or its explicit `--write` alias is
requested. In-place migration creates a backup first.

Generate the editor schema with `nodrix schema --output pipeline.schema.json`.
New project templates include a VS Code YAML mapping automatically.

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
