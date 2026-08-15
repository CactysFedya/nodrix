# Справочник Manifest API v2

Новые manifests:

```yaml
apiVersion: plyctl.dev/v2
kind: Pipeline
```

`nodrix.dev/v1` и `nodrix.dev/v2` остаются поддерживаемыми.

## Полный skeleton

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
streams: {exports: []}
fragments: {}
recording: {}
security: {}
placement: {}
```

## Nodes

```yaml
nodes:
  worker:
    uses: package.module:WorkerNode
    parameters:
      threads: 4
```

`uses` может указывать builtin, provider node ID, `module:Class` или `./file.py:Class`. Старый `use` поддерживается, но для новых manifests рекомендуется `uses` + `parameters`.

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

Policy выбирается по требованиям loss/freshness пути.

## Runtime

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

## Streams

```yaml
streams:
  bind_host: 127.0.0.1
  listen_port: 7420
  exports:
    - name: /example/output
      from: worker.output
      queue: {capacity: 2, policy: latest}
```

## Provider-managed sections

Provider API 2 может описывать resources/sessions, applications и external links. Provider-specific configuration должна быть namespaced и проходить validation до запуска.

## Проверка

```bash
plyctl validate pipeline.yaml
plyctl inspect pipeline.yaml
plyctl plan pipeline.yaml
```
