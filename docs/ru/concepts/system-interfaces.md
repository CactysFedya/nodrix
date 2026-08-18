# Интерфейсы и bindings System

В Nodrix 2.21 вложенная System становится типизированным компонентом. Родитель
настраивает только публичные parameters, resources, inputs и outputs ребёнка;
ребёнок сохраняет собственную revision Definition, Plan, execution context,
lifecycle и границу Run.

```text
описание родителя
  → публичный контракт ребёнка
    → явные bindings
      → рекурсивно разрешённые backend endpoints
```

Planner разрешает эту цепочку до исполнения и никогда не копирует nodes
ребёнка в graph родителя.

## Полный YAML-пример

```yaml
apiVersion: nodrix.system/v1       # Стабильный контракт документа System.
kind: System                       # Документ является System Definition.
name: mapping-stack                # Имя независимо версионируемой Definition.

inputs:                            # Типизированные значения от родителя.
  - name: control                  # Имя публичного входного порта.
    type_id: mapping.control/v1    # Backend-neutral контракт сообщения.

outputs:                           # Типизированные значения для родителя.
  - name: map
    type_id: spatial.metric_map/v1

parameters:                        # Переносимая конфигурация instance.
  - name: voxel_size
    type: number                   # any|string|integer|number|boolean|object|array
    default: 0.2                   # Значение без override родителя.
    description: Размер листа карты в метрах.

resourceRequirements:             # Ресурсы, предоставляемые через границу.
  - name: lidar
    uses: livox.device             # Требуемая identity ResourceDefinition.
    optional: false

resources:                         # Внутренняя реализация requirement.
  - name: internal_lidar
    uses: livox.device

systems:                           # Child Definitions остаются самостоятельными.
  - name: driver                   # Роль instance драйвера LiDAR.
    uses: ./driver.yaml
    resources:
      lidar: internal_lidar        # Requirement ребёнка → ResourceInstance родителя.
  - name: mapper                   # Роль instance в этом родителе.
    uses: ./mapper.yaml            # Разрешается в точную pinned revision.

bindings:                          # Публичный контракт → внутренняя реализация.
  inputs:
    - port: control
      endpoint: system:mapper.control # application.port | graph/node.port | system:child.port
  outputs:
    - port: map
      endpoint: system:mapper.map
  parameters:
    - parameter: voxel_size
      targets:
        - system:mapper.voxel_size # Публичный parameter родителя → parameter ребёнка.
  resources:
    - resource: lidar
      instance: internal_lidar

links:                             # Связи независимо планируемых частей.
  - from: system:driver.cloud      # Публичный output ребёнка.
    to: system:mapper.cloud        # Публичный input ребёнка.
    uses: ros2.topic               # Нужен LocalBackend между runtimes.
    parameters:
      topic: /livox/lidar
```

## Синтаксис endpoints и parameters

У port endpoint есть три канонические формы:

- `application.port` для `ApplicationInstance`;
- `graph/node.port` для node внутри Graph;
- `system:instance.port` для публичного порта вложенной System.

Цели parameter всегда явные:

- `application:name.parameter`;
- `resource:name.parameter`;
- `system:name.parameter`;
- `node:graph/name.parameter`.

Публичный parameter может передаваться нескольким внутренним целям. Внутренняя
цель не может одновременно иметь явное instance-значение или два bindings.
При наличии SDK catalog Nodrix до planning проверяет переносимый тип System
против Python-аннотации SDK.

## Parameters, context и resources

Эти каналы имеют разный смысл:

- `SystemInstance.parameters` — декларативные переносимые значения. Они входят
  в точный Plan и попадают только в объявленные parameter targets;
- `SystemExecutionContext.systems` — operational overrides: environment и
  runtime defaults. Ребёнок наследует родителя и применяет только свою именную
  ветку. Plan хранит digest context, а не секретные значения;
- `SystemInstance.resources` связывает requirement ребёнка с родительским
  `ResourceInstance`. Compiled binding передаёт точную provider-конфигурацию и
  placement backend, объявившему capability `system_resources`.

Прямой resource binding не может пересекать target или backend. Для удалённого
ресурса нужна явная service/application boundary.

## Links и runtime boundaries

Planner разрешает System link через любое число вложенных публичных bindings
до конечных graph/application endpoints. Каждый ребёнок всё равно получает
собственный backend context и lifecycle handle.

Backend обязан объявить `system_interfaces`. LocalBackend преобразует
transport-backed child link в существующий integration-provider contract. Он
возвращает `LOCAL103` для неявной in-memory связи независимых child runtimes:
скрытый flattening изменил бы lifecycle и владение ресурсами.

Указывайте `uses` для каждой LocalBackend-связи между child runtimes и для
каждой cross-target/backend связи. Само cross-target/backend исполнение не
входит в локальную границу релиза 3.0.

## Planning и просмотр

```bash
plyctl system validate systems/mapping-stack.yaml --project .
plyctl system plan systems/mapping-stack.yaml --project . --explain
plyctl system plan systems/mapping-stack.yaml --project . --json
```

`--explain` рекурсивно показывает разрешённые IN/OUT/PAR/RES bindings. JSON
содержит те же контракты и эффективные значения в `inputs`, `outputs`,
`parameters`, `resource_requirements`, `bindings` и каждом child Plan.

Основные стабильные diagnostics: `SYS171`–`SYS180` для child values и SDK
parameter bindings, `PLAN407`–`PLAN413` для ошибок compiled interface,
`BACKEND104`/`BACKEND105` для отсутствующих resource/interface capabilities и
`LOCAL103` для отсутствующего transport LocalBackend.

## Python SDK

```python
from nodrix import (
    SystemBoundaryBindings,
    SystemParameter,
    SystemParameterBinding,
    SystemPort,
    SystemPortBinding,
    SystemResourceBinding,
    SystemResourceRequirement,
)

parameters = (
    SystemParameter(name="voxel_size", type="number", default=0.2),
)
bindings = SystemBoundaryBindings(
    inputs=(
        SystemPortBinding(port="control", endpoint="system:mapper.control"),
    ),
    parameters=(
        SystemParameterBinding(
            parameter="voxel_size",
            targets=("system:mapper.voxel_size",),
        ),
    ),
)
```
