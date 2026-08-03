# Contributing

Contributions should keep the core runtime independent from individual
frameworks and place ecosystem-specific behavior in providers or integration
packages.

## Local checks

```bash
python -m pip install -e ".[dev,docs]"
pytest
ruff check .
sphinx-build -W --keep-going -b html docs docs/_build/site/en/latest
sphinx-build -W --keep-going -b html docs/ru docs/_build/site/ru/latest
```

Before opening a pull request, update tests and the current release notes when a
user-visible behavior changes. Project-wide contribution rules remain in
[`CONTRIBUTING.md`](https://github.com/CactysFedya/nodrix/blob/feature/2.2.0-modular-ros2/CONTRIBUTING.md).
