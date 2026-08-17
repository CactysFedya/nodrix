# Самодокументируемый YAML

Nodrix следует правилу:

> **Self-Describing, but never misleading.**
>
> Самодокументируемый, но никогда не вводящий в заблуждение.

YAML-файлы, создаваемые для непосредственного редактирования пользователем,
могут содержать комментарии, объясняющие назначение файла, связи понятий,
команды и необязательные поля.

Эти комментарии относятся только к authoring-слою. Они не являются частью
канонической модели.

## Два представления

Human-facing scaffold может содержать поясняющие комментарии:

```yaml
# Nodrix System
#
# Что это:
#   System — каноническое определение всей исполняемой системы.
#
apiVersion: nodrix.system/v1
kind: System
name: robot
```

Каноническая сериализация содержит только данные:

```yaml
apiVersion: nodrix.system/v1
kind: System
name: robot
```

Оба файла описывают один и тот же канонический System.

Комментарии не влияют на:

- `EntityRef`
- `RevisionRef`
- identity Definition
- `SystemModel`
- Plan
- Execution
- provenance

## Язык authoring-комментариев

Язык generated comments выбирается в `nodrix.yaml`:

```yaml
schema: nodrix.project/v1

defaults:
  view: compact
  language: ru
```

Сейчас поддерживаются:

```text
en
ru
```

Например:

```bash
plyctl project init robot --language en
plyctl project init robot --language ru
```

Для старых проектов без `defaults.language` используется английский язык.

## Канонический словарь не переводится

Настройка языка изменяет только комментарии.

Канонические ключи и имена типов остаются стабильными:

```yaml
apiVersion: nodrix.system/v1
kind: System
name: robot
targets: []
resources: []
applications: []
```

Поэтому русскоязычный scaffold по-прежнему использует `targets`, `resources`,
`applications`, `System`, `Profile`, `RuntimePreset`, `Definition` и `Plan`.

Это позволяет переносить примеры между русской и английской документацией без
преобразования schema.

## Генерируемые ресурсы проекта

Self-Describing standard сейчас применяется к:

- `System`
- `Workflow`
- `Environment`
- `Profile`

### System

System является канонической исполняемой архитектурой.

Scaffold может объяснять validation, planning, execution, inspection, targets,
resources, applications, graphs и relations.

### Workflow

Workflow представляет конечную инженерную операцию из шагов.

Scaffold может объяснять запуск, привязку к Operation, зависимости, рабочий
каталог, условия, cache и другие необязательные поля.

### Environment

Environment описывает требования к host/process: shell setup files, переменные
окружения, platform constraints и checks.

Environment не является описанием исполняемой архитектуры.

### Profile

Profile является именованным project configuration overlay.

Его необходимо отличать от RuntimePreset:

```text
Profile       = project configuration overlay
RuntimePreset = execution/performance defaults
Environment   = host/process prerequisites
```

Profile не является исполняемым Definition.

## Структура комментариев

Human-facing scaffold при необходимости использует небольшой набор
предсказуемых разделов:

```text
What / Что это
Use it for / Используйте для
Relationship / Связь понятий
Commands / Команды
Optional fields / Необязательные поля
Start simple / С чего начать
```

Не каждый ресурс обязан содержать каждый раздел.

Цель — progressive disclosure, а не полный справочник внутри каждого YAML.

## Каноническое правило

Комментарии generated scaffold могут изменяться без изменения canonical
identity.

Canonical serializers остаются свободными от комментариев, если явно не
запрошено human-facing authoring representation.
