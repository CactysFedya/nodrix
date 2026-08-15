# Первый workspace

Workspace объединяет pipelines с окружением запуска, аппаратным профилем и представлением мониторинга.

## Создание

```bash
mkdir demo-workspace
cd demo-workspace
plyctl workspace init .
```

Структура:

```text
demo-workspace/
├── nodrix.yaml
├── pipelines/
├── configs/
├── environments/
├── profiles/
├── views/
├── tests/
└── .nodrix/              # появляется во время работы
```

Plyctl ищет `nodrix.yaml` вверх по дереву каталогов, поэтому команды можно выполнять и из вложенной папки.

## Просмотр разрешённой конфигурации

```bash
plyctl workspace show
plyctl context list
plyctl context show
plyctl env show
```

Для автоматизации:

```bash
plyctl workspace show --json
plyctl env show --json
```

## Минимальный `nodrix.yaml`

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

Имя файла и schema сохраняют `nodrix` для совместимости 2.x. Новые pipeline-manifest должны использовать `plyctl.dev/v2`.

## Выбор контекста

```bash
plyctl use local
```

Активный context записывается в `.nodrix/context` и имеет приоритет над `defaults.context`.

## Предварительная проверка

```bash
plyctl prepare
```

Команда разрешает workspace, проверяет файлы, каталоги, команды и переменные, подключает setup-скрипты и сообщает выбранный pipeline. Успешный `READY` — стандартный допуск к запуску.
