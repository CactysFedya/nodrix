# Your first pipeline

Create `pipelines/demo.yaml`:

```yaml
apiVersion: plyctl.dev/v2
kind: Pipeline
metadata:
  name: demo

runtime:
  mode: offline
  engine: unified
  type_validation: first

nodes:
  source:
    uses: core.synthetic_source
    parameters:
      count: 5

  delay:
    uses: core.delay
    parameters:
      milliseconds: 2

  console:
    uses: sink.console

edges:
  - from: source.output
    to: delay.input
    queue:
      capacity: 8
      policy: block

  - from: delay.output
    to: console.input
    queue:
      capacity: 8
      policy: block

streams:
  exports: []
fragments: {}
recording: {}
security: {}
placement: {}
```

Make sure `nodrix.yaml` maps the alias:

```yaml
pipelines:
  demo: pipelines/demo.yaml
```

## Validate before execution

```bash
plyctl validate demo
plyctl inspect demo
plyctl plan demo
```

Use this sequence routinely:

- `validate` checks manifest structure, node references, ports, and graph constraints;
- `inspect` explains the graph and its resolved components;
- `plan` shows the execution and memory decisions before launch.

## Run in the foreground

```bash
plyctl run demo
```

A foreground run is best while developing because logs remain attached to the terminal and `Ctrl+C` initiates normal shutdown.

## Run in the background

```bash
plyctl up demo
plyctl ps
plyctl logs -f
plyctl down
```

The supervisor writes runtime state to `.nodrix/supervisor.json` and combined output to `.nodrix/logs/runtime.log`.

## Change queue behavior

For offline processing, `block` preserves every message and propagates backpressure. For a real-time preview where only the newest frame matters, use:

```yaml
queue:
  capacity: 1
  policy: latest
```

Do not choose `latest` for recording or other lossless paths.
