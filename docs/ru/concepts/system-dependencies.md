# Зависимости System и readiness

Nodrix 2.20 позволяет родительской System объявить startup-зависимости между
своими непосредственными дочерними System instances. Контракт не зависит от
backend: в нём нет ROS 2 topics, процессов, сервисов или конкретного железа.

## Authoring-контракт

```yaml
apiVersion: nodrix.system/v1
kind: System
name: mapping

systems:
  - name: sensor              # Имя sibling instance в этой System.
    uses: ./livox.yaml        # Путь или закреплённая revision Definition.
  - name: localization
    uses: ./fast-livo2.yaml
  - name: mapping
    uses: ./mapping.yaml

dependencies:
  - system: localization      # Запустить после выполнения условия.
    requires: sensor          # Непосредственный sibling prerequisite.
    condition: ready          # started | ready | healthy
    timeoutSeconds: 30        # Монотонный deadline для этой связи.
  - system: mapping
    requires: localization
    condition: healthy
    timeoutSeconds: 60
```

`system` и `requires` могут ссылаться только на непосредственные sibling
instances. Ссылка на себя, отсутствующий sibling, повторяющаяся связь и цикл
отклоняются до выполнения. Зависимость не пересекает границу родителя и не
приводит к flattening дочерних plans.

## Условия

- `started`: prerequisite вернула живой System execution handle;
- `ready`: агрегированное `ExecutionObservation.ready` равно `true`;
- `healthy`: агрегированное health равно `healthy`.

Выполненное условие становится startup latch: последующее изменение
observation не отменяет принятое решение о запуске. Непрерывная propagation
ошибок и restart policy относятся к production lifecycle.

Отсутствующее observation не считается успехом. Состояния `failed`,
`unhealthy` и terminal-before-condition немедленно завершают startup ошибкой.
Временные `not ready`, `unknown` и `degraded` ожидаются до deadline связи.

## Planning и выполнение

Planner один раз проверяет dependency graph и записывает
`system_startup.dependencies`, `system_startup.order` и
`system_startup.roots` в `SystemExecutionPlan`. Runtime использует готовую
topology и не строит DAG повторно.

Независимые roots запускаются без ожидания несвязанных веток. Polling
ограничен, использует монотонные часы и не создаёт busy-loop. При startup-ошибке
уже запущенные дочерние System останавливаются в обратном фактическом порядке,
затем останавливаются прямые scopes родителя.

System без `dependencies` сохраняет declaration-order поведение и identity
Plan, существовавшие до 2.20.

## Наблюдение и автоматизация

Во время запуска human-вывод `plyctl system run` показывает `CHILD STARTED`,
`DEPENDENCY WAITING`, `DEPENDENCY SATISFIED` и `DEPENDENCY FAILED`.

Режим `--output jsonl` публикует соответствующие versioned events:

```text
child_started
dependency_waiting
dependency_satisfied
dependency_failed
```

Событие зависимости содержит execution ID родителя, имена child и
prerequisite, условие, timeout, прошедшее время и сообщение ошибки.

## Python SDK

```python
from nodrix import SystemDependency, SystemDependencyCondition

dependency = SystemDependency(
    system="mapping",
    requires="localization",
    condition=SystemDependencyCondition.HEALTHY,
    timeoutSeconds=60,
)
```

Контракт использует стабильные diagnostics: `SYS061`–`SYS064` для ссылок
модели, `PLAN406` для циклов и `ORCH301`–`ORCH305` для timeout, ошибки
prerequisite, unhealthy, отсутствующего observation и некорректного compiled
startup plan.
