# Установка и первый запуск

## Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install plyctl
plyctl --version
```

Для запуска из исходного кода:

```bash
python -m pip install -e ".[dev,docs]"
```

## Создание проекта

```bash
plyctl init demo --template core
cd demo
plyctl validate pipeline.yaml
plyctl inspect pipeline.yaml
plyctl run pipeline.yaml
```

Новые проекты используют `apiVersion: plyctl.dev/v2`. Старые файлы с
`nodrix.dev/v1` или `nodrix.dev/v2` можно продолжать запускать без срочной
миграции.

## Минимальный pipeline

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
edges:
  - from: source.output
    to: sink.input
```

Команда `plyctl schema` создаёт `.plyctl-schema.json` для автодополнения и
проверки YAML в редакторе.
