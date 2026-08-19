# ADR-0003: Execution и Run policy

- **Статус:** Accepted
- **Дата:** 2026-08-19
- **Область:** Nodrix 2.23

## Контекст

Nodrix использует одну canonical модель Execution и Run для run, test,
benchmark, profile, diagnostics и пользовательских операций.

Поэтому cross-domain control-plane настройки не должны дублироваться
отдельными типами Run для каждой операции или попадать в архитектурные
System Definitions.

При этом воспроизводимая история Run должна фиксировать effective policy,
применённую вокруг конкретного execution.

## Решение

### ExecutionPolicy

Nodrix определяет один immutable `ExecutionPolicy`, общий для всех
operation kinds.

Начальная версия содержит:

- `RunEnvironmentPolicy`;
- `RunLogPolicy`.

Это cross-domain control-plane policy.

Она не изменяет semantic contents точного `PlanRecord`.

### Принадлежность

ExecutionPolicy принадлежит Execution / Run policy.

Она не принадлежит `SystemModel` или другому архитектурному Definition.

Поэтому один и тот же System и точный Plan можно выполнять несколько раз
с разной control-plane policy без изменения identity Definition или Plan.

### Настройки, влияющие на execution

Настройки, изменяющие то, что реально выполняется, должны оставаться
частью planning и exact Plan.

Например:

- topology;
- placement;
- dependency semantics;
- queue behavior;
- restart semantics;
- resource constraints, влияющие на execution.

Их нельзя скрыто переносить в ExecutionPolicy.

### Lifecycle Events

Критические lifecycle Events являются обязательными historical evidence.

Поэтому ExecutionPolicy не содержит переключателя `events_enabled`.

### Logs

Подробные диагностические Logs остаются optional и bounded.

`RunLogPolicy` управляет:

- включением логирования;
- minimum level;
- categories;
- total byte limit;
- per-category byte limit;
- per-record byte limit;
- overflow behavior;
- redaction.

Logs остаются отдельной сущностью от Events, Metrics и Artifacts.

### Environment provenance

Runtime environment фиксируется только через явный allowlist.

Полный process environment автоматически не сохраняется.

Effective allowlist и redaction configuration входят в Run policy
provenance.

### Secret material

Literal values из `RedactionPolicy.secrets` никогда не записываются в
`policy.json`.

Вместо этого provenance фиксирует только:

- были ли literal secrets настроены;
- их количество;
- факт того, что значения намеренно не сохранялись.

### Persistent provenance

Persistent Runs формата `nodrix.run-layout/v2` содержат immutable
`policy.json`.

Порядок публикации:

`RunSession -> Definition snapshot -> Plan snapshot -> policy.json
-> environment.json -> backend preparation`.

Ошибка публикации policy provenance не позволяет перейти к backend
preparation.

Run directory сохраняется как evidence неудачной попытки execution.

### Plan identity

ExecutionPolicy намеренно не входит в `PlanRecord.plan_id`.

Поэтому два Runs могут иметь:

- один Definition;
- один exact Plan;
- один Plan ID;
- разную ExecutionPolicy provenance.

Это необходимо для будущего structured Run comparison.

### Совместимость

`nodrix.run-layout/v1` остаётся поддерживаемым immutable historical
форматом.

Для layout v1 наличие `policy.json` не требуется.

Новые persistent Runs используют `nodrix.run-layout/v2`.

Для layout v2:

- отсутствие `policy.json` означает incomplete provenance (`REC107`);
- повреждённый или identity-inconsistent `policy.json` означает
  corruption (`REC410`).

Старые runtime arguments `environment_policy=` и `log_policy=`
временно остаются compatibility surface.

Они детерминированно преобразуются в один effective `ExecutionPolicy`.

Одновременная передача нового `execution_policy=` и legacy policy
arguments запрещена вместо неявного merge/precedence.

## Отложенная работа

Typed Metrics являются отдельной сущностью и будут добавлены отдельно.

Observability profiles minimal, standard, debug и benchmark также
вводятся отдельным контрактом.

Этот ADR не вводит YAML authoring syntax. Создание неописанного YAML
формата здесь нарушило бы правила schema/self-description Nodrix;
authoring/schema binding будет добавлен вместе с контрактом
observability profiles.

## Последствия

- все operation kinds используют одну execution-policy model;
- System Definitions остаются архитектурными, а не operational;
- Plan identity остаётся semantic;
- Run provenance фиксирует фактическую effective control-plane policy;
- исторические Runs v1 остаются читаемыми;
- будущий `runs compare` сможет сравнивать policy differences без
  operation-specific Run types.
