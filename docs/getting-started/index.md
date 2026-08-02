# Getting started

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install plyctl
plyctl --version
```

For a source checkout:

```bash
python -m pip install -e ".[dev]"
```

## Create and run a pipeline

```bash
plyctl init demo --template core
cd demo
plyctl validate pipeline.yaml
plyctl inspect pipeline.yaml
plyctl run pipeline.yaml
```

New projects use `apiVersion: plyctl.dev/v2`. Existing files using
`nodrix.dev/v1` or `nodrix.dev/v2` need no immediate edits.

## Minimal YAML

```yaml
apiVersion: plyctl.dev/v2
kind: Pipeline
metadata:
  name: demo
runtime:
  engine: unified
nodes:
  source:
    uses: core.synthetic_source
    parameters: {count: 10}
  sink:
    uses: core.counter_sink
fragments: {}
edges:
  - from: source.output
    to: sink.input
streams: {}
recording: {}
security: {}
placement: {}
```

Use `plyctl schema` to write `.plyctl-schema.json` for editor completion and
validation.
