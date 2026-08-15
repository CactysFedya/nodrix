# Manifest API v2 reference

New manifests should use:

```yaml
apiVersion: plyctl.dev/v2
kind: Pipeline
```

`nodrix.dev/v1` and `nodrix.dev/v2` remain accepted for 2.x compatibility.

## Complete skeleton

```yaml
apiVersion: plyctl.dev/v2
kind: Pipeline
metadata:
  name: example

runtime:
  mode: offline
  engine: unified
  type_validation: first

nodes: {}
edges: []
streams:
  exports: []
fragments: {}
recording: {}
security: {}
placement: {}
```

The project template writes all top-level v2 sections so manifests remain explicit and forward-compatible.

## Nodes

Canonical form:

```yaml
nodes:
  worker:
    uses: package.module:WorkerNode
    parameters:
      threads: 4
```

`uses` may identify:

- a builtin node such as `core.synthetic_source`;
- a provider node ID;
- `module:Class`;
- `./relative/file.py:Class`.

Compatibility manifests may still use `use` and compact parameter placement, but new manifests should prefer `uses` plus `parameters`.

## Edges

```yaml
edges:
  - from: source.output
    to: worker.input
    queue:
      capacity: 8
      policy: block
    memory:
      mode: auto
```

Ports are written as `NODE.PORT`. Queue policy is semantic and should match the path's loss/freshness requirements.

## Runtime

Common fields:

```yaml
runtime:
  mode: realtime
  engine: unified
  type_validation: first
  metrics:
    enabled: true
    interval_ms: 1000
    listen: 127.0.0.1:9464
```

The unified engine is the default for generated 2.3 projects.

## Streams

```yaml
streams:
  bind_host: 127.0.0.1
  listen_port: 7420
  exports:
    - name: /example/output
      from: worker.output
      queue:
        capacity: 2
        policy: latest
```

## Provider-managed sections

Provider API 2 can describe pipeline-scoped resources/sessions, applications, and external links. Exact fields are validated against provider metadata. Keep provider-specific configuration namespaced and validate before launch.

## Validation workflow

```bash
plyctl validate pipeline.yaml
plyctl inspect pipeline.yaml
plyctl plan pipeline.yaml
```
