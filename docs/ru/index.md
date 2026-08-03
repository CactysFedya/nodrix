# Документация Plyctl

Plyctl — Pipeline OS для локальных и распределённых систем реального времени.
Один типизированный граф управляет Python- и C++-узлами, приложениями ROS 2,
внешними процессами, устройствами и транспортами.

Структура документации повторяет подход ROS 2: установка, последовательные
руководства, практические инструкции, концепции и справочник.

```{toctree}
:maxdepth: 2
:caption: Документация

getting-started/index
tutorials/index
how-to-guides/index
concepts/index
reference/index
integrations/index
contributing
release-notes
```

## Текущая версия

Сайт описывает **Plyctl 2.2.0 alpha.5**. На сайте публикуются заметки только к
актуальной версии. Полная история остаётся в `CHANGELOG.md` и GitHub Releases.

## Совместимость

Plyctl 2.x продолжает читать `nodrix.dev/v1` и `nodrix.dev/v2`. Импорт Python и
CLI-команда `nodrix` остаются совместимыми псевдонимами в течение всей ветки
2.x.
