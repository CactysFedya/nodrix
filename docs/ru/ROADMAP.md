# План Nodrix: от 2.19 до 3.0

Nodrix переходит к description-driven executable architecture:

```text
Description → SystemModel → ExecutionPlan → Backend → Runtime → Run Record
```

Definitions версионируются и воспроизводятся. Вложенная System остаётся
самостоятельным компонентом. Planner один раз вычисляет topology, а runtime
использует готовый Plan. Живое состояние выполнения не записывается в
декларативный YAML. Core не зависит от ROS 2, Dora, CV-фреймворка или
конкретного оборудования.

Для каждого этапа обязательны targeted-тесты, полный suite перед локальным
коммитом, стабильные структурированные diagnostics, синхронная документация
EN/RU и самодокументируемый generated YAML. Удаляется только доказанный
dead/duplicate code.

## Завершённая основа

- **2.19 — иерархическая композиция System:** pinned child Definitions,
  recursive planning, lifecycle и rollback, observation, human status и
  versioned JSONL events.

## Последовательность реализации

- **2.20 — зависимости и readiness:** sibling `SystemDependency`, условия
  `started`/`ready`/`healthy`, deadline каждой связи, поиск циклов, compiled
  deterministic DAG, независимые ветки запуска, bounded polling, propagation
  ошибок, rollback в обратном фактическом порядке и startup events.
- **2.21 — полноценные интерфейсы System:** inputs/outputs, parent-to-child и
  sibling bindings, передача параметров/context/resources, required и optional
  ports, проверка типов и направлений, локальные links и явные transport
  boundaries без скрытого flattening.
- **2.22 — канонический System Run:** versioned run directory с source и
  resolved System, точным Plan/Context, журналом событий, атомарным live/final
  status, environment provenance, redaction, logs и recovery metadata.
- **2.23 — эксплуатационный CLI:** история запусков, status, inspect, logs,
  stop, restart, attach, detach/follow, стабильные форматы и exit codes,
  безопасное идемпотентное управление по Run ID.
- **2.24 — production lifecycle и LocalBackend:** владение process group,
  сигналы, graceful/forced shutdown, отсутствие orphan, stale-run recovery,
  restart policy и backoff, restart подсистемы, isolation и доступные resource
  limits, failure injection и длительные тесты.
- **2.25 — упаковка и переносимость:** wheel/sdist и clean install,
  reproducible/offline dependencies, macOS/Linux, Python 3.12/3.13, подготовка
  aarch64, doctor/preflight, диагностика providers и ROS 2 environment,
  upgrade/rollback установки.
- **2.26 — compatibility и migration:** заморозить границу Pipeline/System,
  сохранить реальные legacy-проекты через явные adapters, автоматизировать
  migration с отчётом о потерях, вести deprecation registry, upgrade schemas и
  hash rules, удалить доказанные dead/duplicate legacy paths.
- **2.27 — security, trust и provenance:** redaction секретов, изоляция
  environment, защита paths/symlinks/archives, checksums и pinned artifacts,
  trust policy providers/resources, безопасные permissions/retention/recovery
  Run и provenance Definition → Plan → Run → Artifact.
- **2.28 — документация и reference-проект:** полные EN/RU руководства по
  архитектуре, SDK, lifecycle, Run, CLI, migration, troubleshooting, security,
  offline и Raspberry Pi; simulated `rpi5-mapping` из отдельных Livox,
  FAST-LIVO2 LIO-only, mapping, monitoring и recording Systems.
- **2.29 — стабилизация и API freeze:** заморозить контракты System, Backend,
  Run и Event; snapshots публичных imports/schema; установка wheel; regressions
  и failure injection; hardware-free soak, performance и leak baselines;
  чистая сборка документации; release и migration notes.

## Граница релиза 3.0

Локальная цель — **3.0.0rc1** без известных P0/P1. Финальный **3.0.0** выходит
только после квалификации на Raspberry Pi: clean install, doctor/planner,
simulated и реальные Livox/FAST-LIVO2/mapping Systems, readiness failures,
restart/recovery, graceful shutdown, detached run, Run records, аппаратный
soak, производительность, память, CPU и температура.

Remote agents, защищённое межхостовое управление, доставка пакетов, cross-host
transport, reconnect и network partitions остаются после 3.0.
