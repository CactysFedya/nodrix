# Nodrix / Plyctl

<p align="center">
  <a href="../README.md">English</a> · <strong>Русский</strong>
</p>

**Nodrix** — экспериментальная платформа исполнения для описания и запуска гетерогенных real-time систем как одной явной и воспроизводимой модели.

Основной публичный Python-пакет и CLI сейчас называются **Plyctl**. Репозиторий сохраняет `nodrix` import/CLI и совместимые контракты на протяжении ветки 2.x.

Проект ориентирован на системы, где Python, C++, ROS 2, отдельные процессы, устройства, транспорты и edge-hardware должны работать вместе без большого количества неявного glue-кода.

## Коротко о проекте

- **Текущий релиз:** `2.8.0`.
- **Языки:** Python 3.11+ и C++20.
- **Модель:** типизированный YAML-граф с nodes, resources, applications и transported edges.
- **Runtime:** local/native execution, process isolation, bounded queues, lifecycle и health.
- **Интеграции:** ROS 2 и spatial/mapping вынесены в отдельные пакеты, а не встроены в ядро.
- **Observability:** runs, metrics, logs, errors, artifacts и diagnostics.
- **Платформы:** Linux x86-64/ARM64, macOS Apple Silicon и Windows x86-64.
- **Edge-проверка:** в release evidence включён hardware smoke на Raspberry Pi 5 / Ubuntu 24.04 / ROS 2 Jazzy.

## Зачем нужен проект

Реальная робототехническая или CV-система обычно состоит не из одного алгоритма:

```text
sensor driver -> preprocessing -> inference -> tracking -> mapping -> output
       |              |              |            |          |
      ROS 2          C++          Python        native      network
```

В обычном проекте эта топология часто размазана по launch-файлам, shell-скриптам, процессам и framework-specific конфигурациям.

Nodrix/Plyctl переносит эти решения в явное исполняемое описание системы:

```text
System description
       |
       v
 validation + resolution
       |
       v
 execution plan
       |
       v
 runtime / backend
       |
       +--> Python nodes
       +--> C++ / native plugins
       +--> managed applications
       +--> ROS 2 integrations
       +--> local / network transports
       |
       v
 run state + metrics + logs + artifacts
```

Проект не пытается заменить ROS 2, inference-frameworks или алгоритмы. Его задача — дать им общую модель исполнения.

## Основные идеи

### Одна явная модель системы

YAML-описание фиксирует, что запускается, как компоненты связаны и какие ресурсы или транспорты им нужны.

```yaml
applications:
  lidar_driver:
    uses: ros2.launch
    bindings: {session: ros}
    package: example_driver
    launch_file: driver.launch.py

nodes:
  mapping:
    uses: ./nodes/mapping.py:MappingNode

edges:
  - from: lidar_driver.points
    to: mapping.points
    transport:
      uses: ros2.topic
      parameters:
        topic: /points
        message_type: sensor_msgs/msg/PointCloud2
```

### Решения runtime должны быть видимыми

Runtime строится вокруг явных контрактов для:

- размера очередей и backpressure;
- копирований и memory domains;
- process isolation;
- lifecycle и health;
- retries/restarts и failure handling;
- local/network путей;
- run artifacts и diagnostics.

### Интеграции остаются модульными

ROS 2, mapping и spatial-функциональность подключаются вокруг core model. Благодаря этому ядро можно использовать и в системах без ROS 2.

## Основные возможности

- Python SDK и CLI;
- native C++20 runner и Plugin C ABI 2;
- типизированное исполнение node/port/edge graph;
- bounded queues и reusable buffer pools;
- shared-memory process isolation;
- CPU/device-memory contracts и DLPack interoperability;
- локальные и LAN streams с явным экспортом;
- recording и воспроизводимые run artifacts;
- lifecycle, health и resource telemetry;
- provider discovery и verification;
- ROS 2 adapters и managed applications;
- planner / diagnose / explain;
- benchmark и сравнение запусков.

## Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install plyctl
plyctl --version
```

Совместимая команда `nodrix` остаётся доступной в ветке 2.x:

```bash
nodrix --version
```

Интеграции устанавливаются отдельно, например:

```bash
pip install plyctl-spatial plyctl-ros2 plyctl-spatial-ros2
```

## Минимальный workflow

```bash
plyctl init my_project
cd my_project

plyctl validate --strict
plyctl lock
plyctl run --locked

plyctl status
plyctl health
```

Диагностика:

```bash
plyctl plan pipeline.yaml
plyctl diagnose runs/RUN-ID
plyctl explain edge source.output:sink.input --pipeline pipeline.yaml
```

## Воспроизводимые Runs

Каждый запуск хранит собственные артефакты вместо зависимости только от вывода терминала:

```text
.nodrix/runs/<run-id>/
├── manifest.yaml
├── resolved-manifest.yaml
├── nodrix.lock
├── runtime.json
├── environment.json
├── status.json
├── metrics.jsonl
├── errors.jsonl
├── logs/
├── outputs/
└── summary.json
```

Это позволяет после завершения процесса восстановить конфигурацию, состояние и результаты запуска и сравнивать их между собой.

## ROS 2 и edge-hardware

Nodrix/Plyctl не является форком и не заменяет ROS 2. ROS 2 остаётся middleware/data plane там, где это нужно, а system model связывает ROS-приложения и обычные процессы в одну исполняемую систему.

Release metadata для `2.8.0` содержит hardware smoke на Raspberry Pi 5 / Ubuntu 24.04 / ROS 2 Jazzy. Semantic mapping при этом явно помечен как experimental.

## Статус проекта

`2.8.0` — alpha software. В проекте есть production-oriented контракты, validation и qualification tooling, но объявленный memory domain сам по себе не означает, что для любого оборудования уже реализован физический zero-copy backend.

Ограничения стараются фиксироваться явно, а не скрывать автоматическим fallback.

## Документация

- [Документация](https://cactysfedya.github.io/nodrix/)
- [Changelog](../CHANGELOG.md)
- [Platform capabilities](PLATFORM_CAPABILITIES.md)
- [Benchmarking](BENCHMARKING.md)
- [Provider API](PROVIDER_API.md)
- [Contributing](../CONTRIBUTING.md)

## Лицензия

Apache License 2.0. См. [LICENSE](../LICENSE).
