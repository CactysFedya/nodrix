# Документация Plyctl 2.3

<div class="plyctl-hero">
<strong>Plyctl — runtime и операционный слой для модульных конвейеров реального времени.</strong><br>
Версия 2.3 добавляет workspace, контексты, воспроизводимые окружения, фоновое управление, операционные представления, управление ROS 2-процессами и интеграцию FAST-LIO2.
</div>

Plyctl позволяет описать граф один раз, проверить его до запуска, выполнять Python- и native-узлы, управлять внешними приложениями и наблюдать систему через единый CLI.

```bash
plyctl workspace init robot-project
cd robot-project
plyctl prepare
plyctl run
```

```{admonition} Имена в серии 2.x
:class: note
Актуальные публичные имена — `Plyctl`, команда `plyctl` и Manifest API `plyctl.dev/v2`. Пакет и команда `nodrix`, старые идентификаторы manifest/provider, файл `nodrix.yaml` и каталог `.nodrix/` сохраняются для совместимости на протяжении всей серии 2.x.
```

## С чего начать

- Новый пользователь: [Установка](getting-started/installation.md) → [Первый workspace](getting-started/first-workspace.md).
- Автор pipeline: [Manifest API v2](reference/manifest.md) и [Python SDK](reference/python-sdk.md).
- Автор интеграции: [Создание provider](tutorials/provider.md) и [Provider SDK](reference/provider-sdk.md).
- Разработчик робота: [ROS 2](integrations/ros2.md) и [FAST-LIO2](integrations/fast-lio2.md).
- Оператор: [Управление workspace](tutorials/workspace-operations.md) и [Эксплуатация](how-to/production.md).

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
```

```{toctree}
:maxdepth: 2
:caption: Интеграции и примеры

integrations/index
integrations/ros2
integrations/fast-lio2
integrations/media
examples/index
```

```{toctree}
:maxdepth: 2
:caption: Проект

releases/index
contributing/index
```
