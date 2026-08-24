# Nodrix

**Executable System Architecture Platform** — платформа для описания, планирования, запуска и наблюдения гетерогенных программных систем.

[English](README.md) · [Русский](README.ru.md) · [Документация](https://cactysfedya.github.io/nodrix/)

[![CI](https://github.com/CactysFedya/nodrix/actions/workflows/ci.yml/badge.svg)](https://github.com/CactysFedya/nodrix/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](pyproject.toml)
[![C++](https://img.shields.io/badge/C%2B%2B-20-blue.svg)](src/nodrix/native)

Nodrix рассматривает работающую систему как **одну исполняемую архитектурную модель**, а не как набор несвязанных launch-скриптов, конфигов, процессов, ROS 2 nodes, benchmark-скриптов и логов.

`plyctl` — основной CLI. Репозиторий и часть compatibility namespace сохраняют историческое имя `nodrix`.

> **Статус разработки**
>
> `main` содержит текущую development line после 2.8, включая direct System runtime, разработанный до внутреннего milestone 2.24. Метаданные опубликованного Python-пакета пока остаются `2.3.0b1`; следующий публичный release ещё не выпущен.

## Основная идея

`System` в Nodrix описывает архитектуру, которая должна существовать во время выполнения:

- targets и execution context;
- resources и общие зависимости;
- applications и исполняемые nodes;
- типизированные связи графа;
- interfaces и границы композиции;
- execution policy;
- observability и данные для воспроизводимости.

Одна и та же модель используется при validation, planning, execution, diagnostics и формировании исторического Run.

```text
System Definition
       │
       ▼
   validation
       │
       ▼
Execution Plan
       │
       ▼
direct runtime materialization
       │
       ├── providers / resources
       ├── nodes / applications
       ├── graph connections
       └── execution environment
       │
       ▼
      Run
       │
       ├── lifecycle events
       ├── typed metrics
       ├── logs
       ├── artifacts
       └── immutable execution record
```

Главный принцип:

> **Система описывается один раз, а выполнение выводится из этой модели.**

## Зачем нужен Nodrix

В робототехнике и real-time проектах быстро появляются отдельные механизмы для:

- запуска Python и C++ компонентов;
- ROS 2 процессов;
- локальных и аппаратно-зависимых конфигураций;
- подготовки environment;
- datasets и artifacts;
- тестов и benchmarks;
- runtime monitoring;
- истории экспериментов.

Nodrix объединяет эти задачи через явные контракты вместо скрытой логики в shell-скриптах и прикладном glue-коде.

Это не замена ROS 2, Docker, CMake или ML framework. Nodrix — слой, который описывает **как независимые компоненты образуют одну исполняемую систему**.

## Каноническая модель выполнения

Текущая архитектура строится вокруг следующей цепочки:

```text
Definition
    ↓
Operation
    ↓
Planner
    ↓
Plan
    ↓
Executor
    ↓
Execution Record
    ↓
Run / History
```

Ключевые свойства:

- **plan before execution** — runtime behavior разрешается заранее и явно;
- **no hidden fallback** — fallback и compatibility behavior должны быть видимы;
- **backend-neutral contracts** — семантика System отделена от механики выполнения;
- **authoring отделён от runtime** — SDK описывает Definitions, но не владеет execution;
- **единая Run model** — обычный run, test, benchmark и diagnostics используют общий execution/history фундамент;
- **структурированная observability** — Events, Metrics, Logs и Artifacts являются разными сущностями.

## System model

Упрощённый пример:

```yaml
apiVersion: nodrix.system/v1
kind: System
metadata:
  name: mapping-stack

targets:
  robot:
    platform: linux-aarch64

resources:
  ros:
    uses: ros2.session

applications:
  lidar:
    target: robot
    uses: ros2.launch
    bindings:
      session: ros

  mapping:
    target: robot
    uses: process

graph:
  edges:
    - from: lidar.points
      to: mapping.points
```

Точная схема находится в [`src/nodrix/schemas/system-v1.schema.json`](src/nodrix/schemas/system-v1.schema.json).

## Direct System runtime

Текущая development line переводит System execution от восстановления legacy pipeline manifests к прямой материализации уже спланированной архитектуры.

Основные части:

```text
src/nodrix/system/
├── planning.py
├── canonical_runtime.py
├── direct_preparation.py
├── direct_materialization.py
├── direct_node_preparation.py
├── direct_node_materialization.py
├── direct_provider_materialization.py
├── direct_edge_materialization.py
├── direct_environment.py
├── direct_executor.py
├── connection_execution.py
├── runtime_mechanics.py
└── validation.py
```

Backend-neutral runtime primitives вынесены отдельно: node loading, process isolation realization, graph validation, provider/edge materialization и transport bindings.

## Run model и observability

История выполнения — часть архитектуры, а не просто набор логов.

Run может хранить:

```text
.nodrix/runs/<run-id>/
├── definition / plan snapshots
├── status
├── execution events
├── metrics
├── logs
├── artifacts
└── final record
```

Поддерживаются:

- append-only lifecycle events;
- bounded/redactable logs;
- typed metrics;
- execution policy и observability profiles;
- immutable final records;
- recovery и integrity validation;
- структурированное сравнение Runs;
- benchmark как обычные Runs плюс агрегированный результат сравнения.

## SDK и расширяемость

Python SDK — это **authoring surface**, а не второй runtime.

Он предоставляет канонические identity/definition primitives для:

- System authoring;
- Workflow authoring;
- Operations;
- custom Definitions;
- extension planners/executors;
- typed messages и resources.

Цель — несколько способов описания системы, которые сходятся в один canonical execution path.

## Robotics и ROS 2

ROS 2 подключается модульно. Nodrix может описывать ROS sessions и applications, не делая ROS 2 частью core object model.

В репозитории есть реальные integration cases для робототехники, включая FAST-LIVO2 / LiDAR mapping и Raspberry Pi 5 qualification. Они используют тот же System model, а не отдельный специальный runtime.

## Структура репозитория

```text
src/nodrix/
├── system/          # System model, planner, validation, direct runtime
├── model/           # canonical object model
├── sdk/             # authoring APIs
├── native/          # C++20 runtime/native components
├── run_*.py         # Run persistence, recovery, metrics, logs, comparison
├── benchmark_*.py   # benchmark execution and aggregation
└── ...

packages/
├── nodrix-ros2/
├── nodrix-mapping/
├── nodrix-mapping-ros2/
└── compatibility/integration packages

docs/                # документация EN/RU и ADR
tests/               # architecture/runtime/compatibility tests
examples/             # примеры
```

## Установка

Опубликованный пакет называется `plyctl`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install plyctl
plyctl --version
```

Разработка из репозитория:

```bash
git clone https://github.com/CactysFedya/nodrix.git
cd nodrix
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Основные CLI команды

```bash
plyctl system validate path/to/system.yaml
plyctl system plan path/to/system.yaml
plyctl system show path/to/system.yaml
plyctl system run path/to/system.yaml
```

Также есть CLI для projects, Runs, operations, benchmarks, diagnostics и development tooling.

## Тестирование

Regression suite покрывает canonical model, границу planning/execution, System composition, direct runtime materialization, Run persistence, metrics, benchmarking, SDK authoring, compatibility и integrations.

Обычные локальные проверки:

```bash
python -m ruff check src tests scripts
python -m pytest -q
```

Часть integration/platform qualification tests требует дополнительных зависимостей или оборудования.

## Документация

Основные точки входа:

- [`docs/index.md`](docs/index.md)
- [`docs/PRINCIPLES.md`](docs/PRINCIPLES.md)
- [`docs/ROADMAP.md`](docs/ROADMAP.md)
- [`docs/CANONICAL_OBJECT_MODEL.md`](docs/CANONICAL_OBJECT_MODEL.md)
- [`docs/CANONICAL_STORAGE_STANDARD.md`](docs/CANONICAL_STORAGE_STANDARD.md)
- [`docs/adr/`](docs/adr/)
- [`docs/ru/`](docs/ru/)

## Статус проекта

Nodrix активно развивается. В репозитории одновременно находятся стабильные compatibility surfaces выпущенных версий и более новая архитектурная работа, которая ещё не опубликована отдельным package release.

Поэтому:

- внутренний milestone не равен версии на PyPI;
- integration examples могут требовать platform-specific dependencies;
- часть compatibility-кода намеренно сохраняется на протяжении перехода 2.x.

## Лицензия

Apache License 2.0. См. [`LICENSE`](LICENSE).
