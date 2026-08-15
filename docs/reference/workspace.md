# Workspace schema reference

## Project file

Filename: `nodrix.yaml`

```yaml
schema: nodrix.project/v1
name: project-name

defaults:
  pipeline: main
  context: local
  view: compact

pipelines:
  main: pipelines/main.yaml

contexts:
  local:
    environment: local
    profile: default
    view: compact
    variables:
      EXTRA_FLAG: "1"
```

### Resolution rules

- A pipeline argument may be a direct path or a key in `pipelines`.
- Without an argument, `defaults.pipeline` is used.
- The active context comes from `.nodrix/context`, then `defaults.context`.
- Environment/profile/view values may be inline mappings, explicit paths, or names resolved from conventional directories.

## Environment document

Convention: `environments/NAME.yaml`

```yaml
schema: nodrix.environment/v1
name: NAME
shell:
  source:
    - /path/to/setup.bash
environment:
  KEY: value
checks:
  - type: file
    path: /required/file
```

Accepted setup fields are `shell.source` and the compatibility `source`. Supported checks are:

| Type | Fields | Success condition |
|---|---|---|
| `file` | `path` | File exists. |
| `directory` | `path` | Directory exists. |
| `command` | `command` | Command exits successfully. |
| `environment` | `name` | Variable exists after environment construction. |

## Profile document

Convention: `profiles/NAME.yaml`

```yaml
schema: nodrix.profile/v1
name: NAME
runtime_profile: realtime-low-latency
variables:
  THREADS: "4"
```

## View document

Convention: `views/NAME.yaml`

```yaml
schema: nodrix.view/v1
name: operations
columns:
  - health
  - cpu
  - memory
  - pid
  - processes
  - threads
  - restarts
```

Built-in view names used by the branch are `compact`, `operations`, and `debug`.

## Injected variables

Plyctl injects at least:

```text
NODRIX_PROJECT_ROOT
NODRIX_PIPELINE
NODRIX_CONTEXT
```

The compatibility prefix is intentional in 2.x.
