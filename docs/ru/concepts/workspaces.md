# Workspace и context

Pipeline manifest описывает поведение графа. Workspace описывает, как этот граф выбирается и запускается на конкретном хосте.

```text
nodrix.yaml                 aliases и contexts
pipelines/*.yaml            графы
environments/*.yaml         setup, variables, checks
profiles/*.yaml             hardware/runtime tuning
views/*.yaml                колонки мониторинга
.nodrix/                    context, runs, logs, supervisor state
```

## Модель resolution

Plyctl ищет `nodrix.yaml` вверх, затем разрешает:

1. аргумент pipeline, alias или default;
2. active context из `.nodrix/context` или defaults;
3. environment, profile и view контекста;
4. inline document, path или файл из conventional directory;
5. variables и substitutions;
6. setup scripts и checks.

Прямой путь к pipeline работает и без workspace.

## Context как режим эксплуатации

- `local`: ноутбук, default profile, compact view;
- `robot`: ROS 2, sensor profile, operations view;
- `simulation`: simulator, simulated time, debug view.

Context должен описывать целостную цель запуска, а не одиночный временный flag.
