# Участие в разработке

Интеграции для конкретных экосистем следует размещать в провайдерах и отдельных
пакетах, сохраняя независимость core runtime.

Перед pull request выполните:

```bash
python -m pip install -e ".[dev,docs]"
pytest
ruff check .
sphinx-build -W --keep-going -b html docs docs/_build/site/en/latest
sphinx-build -W --keep-going -b html docs/ru docs/_build/site/ru/latest
```
