# Публикация Nodrix на GitHub и PyPI

## Что уже настроено

- пакет PyPI называется `nodrix`;
- установка: `pip install nodrix`;
- CLI: `nodrix` и `nodrix-viewer`;
- репозиторий: `CactysFedya/nodrix`;
- CI проверяет Python 3.11–3.14 и C++ runtime;
- workflow `publish.yml` собирает Linux x86-64, Linux ARM64, macOS Apple
  Silicon и Windows x86-64 wheels;
- публикация использует PyPI Trusted Publishing через OIDC;
- после успешной загрузки автоматически создаётся GitHub Release.

## 1. Локальная проверка

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,all]"
pytest -q
make native-test
python -m build
python -m twine check dist/*
```

## 2. Создание GitHub-репозитория

Авторизуй GitHub CLI:

```bash
gh auth login
```

Из корня проекта:

```bash
scripts/create_github_repo.sh CactysFedya nodrix public
```

Ручной эквивалент:

```bash
git branch -M main
git remote add origin git@github.com:CactysFedya/nodrix.git
git push -u origin main
```

## 3. Настройка PyPI Trusted Publisher для первой публикации

На PyPI открой настройки публикации и создай pending Trusted Publisher:

```text
PyPI project name: nodrix
Owner:             CactysFedya
Repository:        nodrix
Workflow:          publish.yml
Environment:       pypi
```

На GitHub создай environment `pypi`:

```text
Repository → Settings → Environments → New environment → pypi
```

Рекомендуется включить Required reviewers. Секрет `PYPI_TOKEN` добавлять не нужно.

## 4. Релиз 2.1.0

Версию 2.0.0 повторно публиковать нельзя. После merge ветки 2.1.0 в `main`
и успешного CI:

```bash
git switch main
git pull --ff-only
python3 scripts/check_release.py
git tag -s v2.1.0 -m "Nodrix 2.1.0"
```

Если GPG-подпись не настроена:

```bash
git tag -a v2.1.0 -m "Nodrix 2.1.0"
```

Затем:

```bash
git push origin v2.1.0
```

GitHub Actions автоматически:

1. проверит соответствие тега версии;
2. повторит lint, полный Python suite, million-message stress и CTest;
3. соберёт и проверит канонический sdist;
4. соберёт все platform wheels именно из этого sdist;
5. загрузит дистрибутивы на PyPI;
6. создаст GitHub Release и приложит файлы.

Проверка после публикации:

```bash
python3 -m venv /tmp/nodrix-pypi
source /tmp/nodrix-pypi/bin/activate
pip install nodrix
nodrix --version
```

Viewer и Media Pack:

```bash
pip install "nodrix[viewer]"
pip install "nodrix[media]"
```

## 5. Следующие релизы

```bash
scripts/release.sh X.Y.Z
```

Перед запуском добавь секцию `## X.Y.Z` в `CHANGELOG.md`. Скрипт обновит
версии, создаст commit/tag и отправит их в GitHub.

PyPI запрещает перезаписывать уже опубликованную версию. Любое исправление требует новой версии.

## Ручная загрузка как аварийный вариант

Trusted Publishing предпочтительнее. Для ручной публикации:

```bash
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

Используй project-scoped PyPI API token и не сохраняй его в репозитории или `.pypirc` внутри проекта.

## Матрица 2.x

Релиз собирает wheels для Linux x86-64, Linux ARM64, macOS Apple Silicon и
Windows x86-64. Каждый wheel обязан содержать
`nodrix/bin/nodrix-native-runner`; macOS Intel не входит в обязательную матрицу
2.x.
