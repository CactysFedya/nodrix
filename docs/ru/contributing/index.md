# Разработка документации

## Правила

- Описывать только поведение целевой ветки.
- Для новых примеров использовать `Plyctl`, `plyctl`, `plyctl.dev/v2`.
- Compatibility identifiers объяснять, а не молча переименовывать.
- Разделять tutorials, how-to, concepts и reference.
- Команды должны быть выполняемыми или явно помеченными как schematic.
- Пути EN/RU страниц желательно держать одинаковыми.
- Не создавать страницу для каждого patch release.

## Сборка

```bash
python -m pip install -e '.[docs]'
sphinx-build -W --keep-going -b html docs docs/_build/site/en/latest
sphinx-build -W --keep-going -b html docs/ru docs/_build/site/ru/latest
```

Для простого изменения Markdown локальная сборка необязательна. GitHub Actions собирает обе версии и считает warnings ошибками.
