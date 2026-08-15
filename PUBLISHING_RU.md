# Публикация Plyctl на GitHub и PyPI

## Что уже настроено

- пакет PyPI называется `plyctl`;
- установка: `pip install plyctl`;
- CLI: `plyctl` и `plyctl-viewer`;
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
NODRIX_BUILD_NCNN_PLUGIN=1 NODRIX_FETCH_NCNN=1 python -m build
python -m twine check dist/*
```

Для полной локальной NCNN-проверки используйте закреплённый исходник и
`scripts/ncnn_smoke.py`; точная команда и модель приведены в
`docs/NATIVE_NCNN_QUALIFICATION.md`.

## 2. Создание GitHub-репозитория

Авторизуй GitHub CLI:

```bash
gh auth login
```

Из корня проекта:

```bash
scripts/create_github_repo.sh CactysFedya plyctl public
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
PyPI project name: plyctl
Owner:             CactysFedya
Repository:        plyctl
Workflow:          publish.yml
Environment:       pypi
```

Тот же publisher для `publish.yml` нужно разрешить для `nodrix` и четырёх
модульных проектов: `plyctl-spatial`, `plyctl-mapping`, `plyctl-ros2` и
`plyctl-spatial-ros2`. Пакет `nodrix` — маленький compatibility installer,
который зависит от точно такой же версии `plyctl`.

Для четырёх модульных проектов дополнительно разреши тот же repository и
environment, но workflow укажи `publish-modular-package.yml`. Это позволяет
выпускать отдельный пакет независимо от ядра.

На GitHub создай environment `pypi`:

```text
Repository → Settings → Environments → New environment → pypi
```

Рекомендуется включить Required reviewers. Секрет `PYPI_TOKEN` добавлять не нужно.

## 4. Релиз 2.2.0a5

После merge alpha.5 в основную ветку и успешного CI:

```bash
git switch main
git pull --ff-only
python3 scripts/check_release.py
git tag -s v2.2.0a5 -m "Plyctl 2.2.0a5"
```

Если GPG-подпись не настроена:

```bash
git tag -a v2.2.0a5 -m "Plyctl 2.2.0a5"
```

Затем:

```bash
git push origin v2.2.0a5
```

GitHub Actions автоматически:

1. проверит соответствие тега версии;
2. повторит lint, полный Python suite, million-message stress, CTest и
   реальную сборку/smoke-проверку NCNN;
3. соберёт и проверит канонический sdist;
4. соберёт все platform wheels именно из этого sdist и проверит наличие
   нативного NCNN provider в каждом wheel;
5. загрузит дистрибутивы на PyPI;
6. создаст GitHub Release и приложит файлы.

Проверка после публикации:

```bash
python3 -m venv /tmp/plyctl-pypi
source /tmp/plyctl-pypi/bin/activate
pip install plyctl
plyctl --version
```

Viewer и Media Pack:

```bash
pip install "plyctl[viewer]"
pip install "plyctl[media]"
```

## 5. Следующие релизы

```bash
scripts/release.sh X.Y.Z
```

Перед запуском добавь секцию `## X.Y.Z` в `CHANGELOG.md`. Скрипт обновит
версии, создаст commit/tag и отправит их в GitHub.

PyPI запрещает перезаписывать уже опубликованную версию. Любое исправление требует новой версии.

Отдельный модуль публикуется собственным тегом после изменения его версии в
`pyproject.toml` и успешного modular CI:

```bash
git tag -a plyctl-ros2-v0.4.1 -m "plyctl-ros2 0.4.1"
git push origin plyctl-ros2-v0.4.1
```

Допустимые префиксы: `plyctl-spatial-v`, `plyctl-mapping-v`,
`plyctl-ros2-v` и `plyctl-spatial-ros2-v`. Workflow сверяет имя и версию тега
с метаданными выбранного пакета, тестирует весь модульный набор и публикует
только выбранный wheel/sdist.

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
