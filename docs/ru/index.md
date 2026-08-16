# Документация Plyctl 2.3

<div class="plyctl-hero">
<strong>Plyctl — runtime и операционный слой для модульных конвейеров реального времени.</strong><br>
Версия 2.3 добавляет workspace, контексты, воспроизводимые окружения, фоновые операции, operator views, управление ROS 2-процессами и квалифицируемые reference integrations.
</div>

Plyctl позволяет описать граф один раз, проверить его до запуска, выполнять Python- и native-узлы, управлять внешними приложениями и наблюдать систему через единый CLI.

```bash
plyctl workspace init robot-project
cd robot-project
plyctl prepare
plyctl run
```

```{admonition} Статус beta 2.3.0b1
:class: note
`2.3.0b1` стабилизирует загрузку локальных Python nodes, release metadata и двуязычную документацию. FAST-LIVO2 semantic mapping имеет hardware-smoke evidence на Raspberry Pi 5, но остаётся экспериментальным до закрытия release blockers.
```

```{admonition} Имена в серии 2.x
:class: note
Актуальные публичные имена — `Plyctl`, команда `plyctl` и Manifest API `plyctl.dev/v2`. Пакет и команда `nodrix`, старые идентификаторы manifest/provider, файл `nodrix.yaml` и каталог `.nodrix/` сохраняются для совместимости на протяжении всей серии 2.x.
```

## С чего начать

- Новый пользователь: [Установка](getting-started/installation.md) → [Первый workspace](getting-started/first-workspace.md).
- Автор pipeline: [Manifest API v2](reference/manifest.md) и [Python SDK](reference/python-sdk.md).
- Автор интеграции: [Создание provider](tutorials/provider.md) и [Provider SDK](reference/provider-sdk.md).
- Разработчик робота: [ROS 2](integrations/ros2.md), [FAST-LIO2](integrations/fast-lio2.md) и [qualification FAST-LIVO2 semantic mapping](integrations/fast-livo2-semantic-mapping.md).
- Оператор: [Управление workspace](tutorials/workspace-operations.md), [Эксплуатация](how-to/production.md) и [Перенос на другое устройство](how-to/portable-deployment.md).

```{toctree}
:maxdepth: 2
:caption: Начало работы

getting-started/index
getting-started/installation
getting-started/first-workspace
getting-started/first-pipeline
getting-started/next-steps
```

```{toctree}
:maxdepth: 2
:caption: Учебные руководства

tutorials/index
tutorials/workspace-operations
tutorials/python-node
tutorials/provider
tutorials/ros2-fastlio2
```

```{toctree}
:maxdepth: 2
:caption: Практические инструкции

how-to/index
how-to/environments
how-to/background
how-to/debug
how-to/production
how-to/portable-deployment
```

```{toctree}
:maxdepth: 2
:caption: Основные понятия

concepts/index
concepts/workspaces
concepts/runtime
concepts/providers
```

```{toctree}
:maxdepth: 2
:caption: Справочник

reference/index
reference/cli
reference/workspace
reference/manifest
reference/python-sdk
reference/provider-sdk
reference/plugin-sdk
reference/compatibility
reference/stabilization-register
```

```{toctree}
:maxdepth: 2
:caption: Интеграции и примеры

integrations/index
integrations/ros2
integrations/fast-lio2
integrations/fast-livo2-semantic-mapping
integrations/media
examples/index
```

```{toctree}
:maxdepth: 2
:caption: Проект

PRINCIPLES
COMPATIBILITY
adr/README
planning/index
releases/index
contributing/index
```

- <a href="../../en/latest/">English documentation</a>
