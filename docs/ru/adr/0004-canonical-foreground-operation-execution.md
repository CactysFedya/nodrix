# ADR-0004: Каноническое foreground-выполнение Operation

- **Статус:** Accepted
- **Дата:** 2026-08-19
- **Область:** Nodrix 2.23

## Контекст

Nodrix использует одну canonical execution model:

`Operation -> PlanRecord -> ExecutionRecord -> RunRecord`.

Workflow, benchmark, optimization и extension-backed Operations уже
использовали эти canonical records, однако их внешние сервисы независимо
связывали execution с persistent Run history.

Такое дублирование позволяло разным operation domains постепенно получить
разные lifecycle и persistence semantics при одинаковой canonical model.

Также перед будущими scheduling, remote execution или asynchronous
control-plane возможностями Nodrix нужен явный foreground contract.

## Решение

### Один foreground persistence boundary

Nodrix определяет `persist_foreground_execution()` как общий boundary
между выполненным exact Plan и canonical Run persistence.

Он принимает:

- один exact `PlanRecord`;
- один `ExecutionRecord`, полученный из этого exact Plan;
- optional canonical Run persistence inputs: summary, metadata,
  materialized inputs/outputs и additional provenance.

Результатом является service-level `ForegroundOperationResult`,
содержащий:

- exact Plan;
- exact ExecutionRecord;
- сохранённую canonical Run history.

`ForegroundOperationResult` не является новой canonical persistent
сущностью.

Persistent history по-прежнему представлена `RunRecord`.

### Инвариант exact Plan

Foreground persistence требует:

`execution.plan is plan`.

Execution, созданный для другого PlanRecord, нельзя сохранить через этот
foreground boundary.

Таким образом фиксируется именно exact Plan identity, а не только
равенство похожих значений.

### Инвариант terminal execution

Foreground persistence принимает только terminal `ExecutionRecord`.

Running, prepared или другой non-terminal execution не может стать
завершённым foreground Operation result.

Canonical Run persistence остаётся после terminal execution.

### Registered extension Operations

Registered extension Operations используют полный generic path:

`Operation
-> ExtensionDispatcher.plan()
-> PlanRecord
-> ExtensionDispatcher.execute()
-> ExecutionRecord
-> persist_foreground_execution()
-> RunRecord`.

Planning и execution выполняются явно, чтобы exact PlanRecord оставался
first-class boundary value.

### Built-in domain Operations

Workflow, benchmark и optimization сохраняют свои domain-specific
planners и executors.

Они подключаются к общему foreground path после получения
`ExecutionRecord` от своего executor.

Это намеренное решение.

Domain-specific executor arguments, например benchmark output locations,
не должны попадать в generic extension contract
`PlanExecutor.execute(plan)`.

Поэтому Nodrix не заставляет все built-in executors проходить через
`ExtensionDispatcher`.

### Владение persistence

Domain Operation services не должны напрямую вызывать
`persist_execution()`.

Direct canonical execution-history persistence принадлежит общему
foreground boundary.

Layering:

`domain Operation service
-> foreground boundary
-> execution history
-> RunRecord`.

### CLI boundary

CLI-команды вызывают domain Operation services.

CLI не должен напрямую вызывать:

- `persist_execution()`;
- `persist_foreground_execution()`;
- `execute_foreground_operation()`.

Таким образом CLI остаётся presentation/control input, а не частью Run
persistence architecture.

### Только foreground semantics

Этот ADR не вводит:

- background execution mode;
- detach mode;
- daemon Operation;
- Job entity;
- scheduler;
- remote queue;
- process supervisor contract.

Foreground Operation call возвращается только после перехода execution в
terminal canonical state и успешного Run persistence.

Будущее asynchronous execution может использовать ту же canonical
Operation/Plan/Execution/Run model, но требует отдельного явного
контракта.

### Независимость от OperationKind

Foreground boundary не зависит от `OperationKind`.

Run, test, benchmark, profile, diagnostics и custom Operations не
получают разные фундаментальные Execution или Run types.

Domain-specific behavior принадлежит planning и execution, а не
параллельным lifecycle models.

### ExecutionPolicy

`ExecutionPolicy` остаётся отдельным cross-domain Execution / Run policy
contract из ADR-0003.

Foreground execution не переносит policy в System Definition, Plan
identity или operation-specific result types.

## Последствия

- canonical Run persistence имеет один foreground ownership boundary;
- exact Plan identity проверяется до persistence;
- только terminal executions превращаются в persisted foreground results;
- built-in domains сохраняют специализированную execution semantics;
- extension dispatcher остаётся свободным от persistence;
- CLI находится выше domain Operation services;
- все Operation kinds используют один Execution и Run lifecycle;
- future asynchronous execution нельзя добавить скрытым boolean switch в
  этот contract.
