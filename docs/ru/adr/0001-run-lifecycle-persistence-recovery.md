# ADR-0001: Lifecycle, хранение и recovery для Run

- **Статус:** Accepted
- **Дата:** 2026-08-19
- **Область:** Nodrix 2.22

## Контекст

Nodrix использует единый канонический путь execution:

Description -> SystemModel / Definition -> ExecutionPlan -> Backend -> Runtime -> Run

Версия 2.22 делает Run persistent и self-describing записью execution.

Persistence должна сохранять точный provenance, не превращая high-volume
runtime data в дорогую control-plane history.

## Решение

### Execution authority

`ExecutionPlan` является единственным execution input runtime.

`SystemModel` может передаваться при запуске persistent Run только как
Definition provenance. Runtime не должен перечитывать YAML, заново вычислять
topology или выполнять replanning из Definition.

Каноническая связь provenance:

Definition -> Plan -> Execution -> Run

### Persistent Run layout

Persistent Run session создаётся до backend preparation.

Run directory содержит файлы, появляющиеся согласно lifecycle:

- `session.json` — immutable identity Run и точного Plan.
- `definition.json` — immutable canonical Definition provenance.
- `plan.json` — immutable exact resolved Plan.
- `environment.json` — immutable minimal environment provenance.
- `events.jsonl` — append-only lifecycle/control-plane history.
- `status.json` — atomically replaced mutable operational cache.
- `logs/` — optional bounded diagnostics.
- `run.json` — immutable terminal Run record.

Не все файлы обязаны существовать на каждой стадии lifecycle.

### Provenance

Mandatory pre-execution provenance сохраняется до начала backend execution.

Ошибка его persistence блокирует persistent execution.

Environment capture по умолчанию минимален. Переменные процесса сохраняются
только через explicit allowlist и проходят redaction.

Полный `os.environ` базовым контрактом не сохраняется.

### Events

`events.jsonl` является append-only historical evidence.

Events описывают lifecycle и control-plane facts. Application messages и
high-volume data-plane payloads автоматически в него не попадают.

ROS 2 topics, point clouds, images, sensor streams и подобные потоки остаются в
native data plane, если пользователь явно не сохраняет их как отдельные
artifacts.

### Status

`status.json` является mutable cache для быстрых operational reads.

Это не canonical history и не heartbeat.

`updatedAt` означает последнее persisted изменение status. Его возраст сам по
себе не позволяет считать Run interrupted.

Status reconstructible из durable Run history.

### Logs

Logs являются optional bounded diagnostics и отделены от:

- Events;
- Metrics;
- Artifacts;
- data-plane payloads.

Ошибка optional logging не управляет execution.

Это best-effort правило не относится к mandatory provenance.

### Final Run record

`run.json` immutable и публикуется только после terminal `ExecutionRecord`.

Reader отклоняет corrupted identity, неправильную terminal semantics,
нестандартные JSON numbers, timestamps без timezone и interval, где
`finishedAt` раньше `startedAt`.

Ошибка до фактического старта execution может корректно оставить Run без
`run.json`.

## Recovery semantics

Recovery является read-only интерпретацией durable Run state.

Recovery не выполняет restart, reattach, process ownership, supervision и не
переписывает historical evidence.

Persisted non-terminal Run по умолчанию имеет классификацию
`active-or-unknown`.

`interrupted` допустим только если внешний owner-aware context явно знает, что
live execution owner отсутствует.

Возраст `status.updatedAt` не является достаточным доказательством.

## Производительность и безопасность

Run persistence рассчитан на low-resource hosts:

- lifecycle Events являются малыми control-plane records;
- status — один replaceable cache;
- logging по умолчанию отключён и bounded при включении;
- environment capture использует allowlist;
- high-volume traffic остаётся вне canonical Run history.

Риск сохранения secrets снижается allowlisted environment capture и redaction.

Mandatory historical provenance работает fail-closed. Optional diagnostics
работают fail-open относительно execution availability.

## Совместимость

ADR фиксирует Run contract, формируемый для архитектуры Nodrix 3.0.

Legacy Pipeline execution может временно оставаться за compatibility boundaries
во время перехода 2.x, но canonical Run persistence не должен зависеть от
legacy manifest semantics.

Будущие detached execution и supervision требуют отдельного ownership/liveness
contract и не должны молча трактовать `status.updatedAt` как heartbeat.

Metrics и Artifacts остаются отдельными контрактами.

## Validation evidence

Тесты Nodrix 2.22 покрывают создание Run, Events, Status, immutable final
records, Definition и Plan snapshots, environment redaction, bounded logs,
recovery настоящих Runs, strict JSON, timestamps, chronology и provenance
consistency.

Acceptance regression:

1510 passed, 3 skipped, 7 known pre-existing warnings.
