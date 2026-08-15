# Справочник workspace schemas

## `nodrix.yaml`

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

Pipeline может быть прямым path или alias. Active context берётся из `.nodrix/context`, затем из defaults. Environment/profile/view разрешаются из inline mapping, explicit path или conventional directory.

## Environment

`environments/NAME.yaml`:

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

Поддерживаются `shell.source` и compatibility `source`.

| Type | Поля | Успех |
|---|---|---|
| `file` | `path` | Файл существует. |
| `directory` | `path` | Каталог существует. |
| `command` | `command` | Команда завершилась успешно. |
| `environment` | `name` | Переменная существует после сборки environment. |

## Profile

```yaml
schema: nodrix.profile/v1
name: NAME
runtime_profile: realtime-low-latency
variables:
  THREADS: "4"
```

## View

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

В ветке используются `compact`, `operations`, `debug`.

## Injected variables

```text
NODRIX_PROJECT_ROOT
NODRIX_PIPELINE
NODRIX_CONTEXT
```

Compatibility prefix сохраняется в 2.x.
