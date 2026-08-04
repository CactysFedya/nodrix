# Your first workspace

A workspace groups pipelines with their execution environment, hardware profile, and operational view.

## Create it

```bash
mkdir demo-workspace
cd demo-workspace
plyctl workspace init .
```

The generated layout is:

```text
demo-workspace/
├── nodrix.yaml
├── pipelines/
├── configs/
├── environments/
├── profiles/
├── views/
├── tests/
└── .nodrix/              # created at runtime
```

Plyctl searches upward from the current directory for `nodrix.yaml`, so commands also work from a nested folder.

## Inspect resolution

```bash
plyctl workspace show
plyctl context list
plyctl context show
plyctl env show
```

`workspace show` displays the final pipeline, context, environment, profile, runtime profile, and view. Use JSON when automation needs stable output:

```bash
plyctl workspace show --json
plyctl env show --json
```

## Understand `nodrix.yaml`

A minimal project file looks like this:

```yaml
schema: nodrix.project/v1
name: demo-workspace

defaults:
  pipeline: demo
  context: local
  view: compact

pipelines:
  demo: pipelines/demo.yaml

contexts:
  local:
    environment: local
    profile: default
    view: compact
```

The filename and schema retain `nodrix` for 2.x compatibility. New manifests should use `plyctl.dev/v2`.

## Select a context

```bash
plyctl use local
```

The active context is stored in `.nodrix/context`. It overrides `defaults.context` until another context is selected.

## Run preflight checks

```bash
plyctl prepare
```

`prepare` resolves the workspace, checks declared files, directories, commands, and environment variables, sources configured setup scripts, and reports the selected pipeline. Treat a successful `READY` result as the normal gate before launch.
