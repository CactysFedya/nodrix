# Pipeline Manifest

```yaml
apiVersion: nodrix.dev/v1
kind: Pipeline
metadata:
  name: example
runtime:
  engine: unified
  mode: realtime
nodes: {}
edges: []
streams:
  exports: []
```

Один output port может иметь несколько edges и несколько экспортированных
streams.

```yaml
streams:
  exports:
    - name: /camera/front
      from: camera.frame
      queue: {capacity: 1, policy: latest}
```
