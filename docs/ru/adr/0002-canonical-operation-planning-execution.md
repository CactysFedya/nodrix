# ADR-0002: Канонический контракт Operation, planning и execution

- **Статус:** Accepted
- **Дата:** 2026-08-19
- **Область:** Nodrix 2.23

## Контекст

Nodrix поддерживает разные инженерные действия: run, build, test, profile,
benchmark, diagnostics, calibration, export, packaging, cleanup и
пользовательские операции.

Эти действия не должны создавать отдельные execution architecture.

Канонический operational path:

Operation -> OperationPlanner -> PlanRecord -> PlanExecutor
-> ExecutionRecord -> RunRecord

## Решение

### Operation

`Operation` описывает только intent.

Он содержит:

- расширяемый `OperationKind`;
- canonical subject;
- optional subject revision;
- operation-specific parameters.

Operation не хранит backend state, execution state, process handles,
timestamps, executor identity или Run identity.

`OperationKind` является расширяемым типом, а не закрытым Enum.
Пакеты могут вводить namespaced kinds без изменения Nodrix Core.

### Planning

Resolution revision принадлежит planning.

Поэтому `Operation.subject_revision` может отсутствовать в исходном
request.

Полученный `PlanRecord` обязан фиксировать immutable
`subject_revision`.

`OperationPlanner` получает:

- один `Operation`;
- один explicit `PlanningContext`.

Planning policy не должна скрываться внутри execution.

Planner не должен неявно определять project root, сканировать произвольное
storage, перечитывать execution configuration или зависеть от mutable
ambient state, если эти данные должны быть переданы через resolved planning
context.

### Plan

`PlanRecord` является resolved execution authority операции.

Он фиксирует:

- Plan identity;
- Plan kind;
- исходный Operation;
- exact resolved subject revision;
- domain-specific resolved payload;
- metadata.

Planning и execution являются разными стадиями.

### Execution

`PlanExecutor.execute()` принимает `PlanRecord` и возвращает
`ExecutionRecord`.

Executor не принимает Operation или Definition как альтернативный
execution input.

`ExecutionRecord` ссылается на точный выполненный Plan.

Operation и subject provenance получаются через Plan и не копируются в
отдельные mutable поля.

### Run

Все operation kinds используют один canonical `ExecutionRecord` и один
canonical `RunRecord`.

Core не создаёт фундаментальные operation-specific типы:

- `BenchmarkRunRecord`;
- `TestRunRecord`;
- `ProfileRunRecord`;
- `DiagnosticsRunRecord`.

Domain-specific результаты принадлежат typed records, Metrics, Artifacts,
Relations, execution details или aggregate results, а не второй иерархии
Run.

### Built-in и custom operations

Nodrix задаёт conventional operation kinds:

- prepare;
- build;
- test;
- validate;
- run;
- profile;
- benchmark;
- optimize;
- diagnose;
- calibrate;
- export;
- package;
- cleanup.

Этот список является набором conventions, а не закрытым universe.

Пакеты могут вводить kinds вроде `vendor.hardware-check` или
`slam.evaluate`.

Custom Operation всё равно использует тот же canonical Plan, Execution и
Run model.

### Dispatcher

Canonical dispatcher явно разделяет planning и execution.

`dispatch(operation, context)` эквивалентен:

`plan(operation, context)` и затем `execute(plan)`.

Dispatcher проверяет:

- planner вернул Plan для исходного Operation;
- executor вернул Execution для выбранного Plan;
- executor identity соответствует выбранному executor.

### Benchmark и test semantics

Benchmark, test, profile, diagnostics и другие домены могут иметь свои
planners, executors, Metrics, Artifacts и aggregate results.

Они не получают отдельные Core execution или Run models.

В последующих контрактах Nodrix benchmark рассматривается как обычные Runs
плюс structured aggregate comparison, а не отдельный runtime.

## Совместимость

Существующие workflow, benchmark, optimization и extension execution paths
уже используют canonical Operation / Plan / Execution model.

Legacy Pipeline execution может временно оставаться за compatibility
boundaries во время перехода 2.x, но не должно переопределять этот
canonical operational contract.

## Validation evidence

Nodrix 2.23.1 добавляет architecture invariants для:

- unresolved Operation intent;
- mandatory resolved Plan revision;
- Execution provenance через Plan;
- Run provenance через Execution;
- extensible Operation kinds;
- explicit PlanningContext;
- Plan-only executor input;
- разделения planning/execution;
- отсутствия operation-specific Core Run types.

Результат operation architecture regression:

124 passed.
