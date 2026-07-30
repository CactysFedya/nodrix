# Офлайн-установка Nodrix 2.1.0

Nodrix сохраняет минимальное требование build backend `setuptools>=68` и не
требует нового парсера SPDX только для чтения лицензии. Это позволяет собирать
проект на Ubuntu 24.04/Raspberry Pi без обращения к PyPI, если основные
зависимости уже перенесены локально.

## Быстрая установка из исходников

В каталоге репозитория:

```bash
python3 -m pip install . \
  --no-build-isolation \
  --no-deps \
  --break-system-packages
```

Или через проверяющий скрипт:

```bash
scripts/install_offline.sh
```

Скрипт сначала проверяет локальное наличие `setuptools`, `wheel`, `typer`,
`pydantic`, `PyYAML`, `rich`, `packaging`, CMake и C++20-компилятора. Затем он
компилирует пять Python C++-расширений и упакованный standalone native runner
без сетевых запросов. Базовая сборка из исходников не включает NCNN
автоматически, потому что его исходный код нельзя незаметно скачивать при
офлайн-установке.

Для сборки нативного NCNN provider заранее перенесите проверенное дерево
исходников NCNN 20260526 и задайте:

```bash
NODRIX_BUILD_NCNN_PLUGIN=1 \
NODRIX_FETCH_NCNN=0 \
NODRIX_NCNN_SOURCE_DIR=/opt/src/ncnn-20260526 \
  scripts/install_offline.sh
```

Официальные platform wheels уже содержат этот provider и не требуют
компилятора или исходников NCNN при установке.

## Перенос зависимостей

На компьютере с интернетом скачайте зависимости в каталог `wheelhouse`:

```bash
python3 -m pip download \
  --dest wheelhouse \
  -r offline-requirements.txt
```

Скопируйте на целевое устройство:

```text
nodrix/
wheelhouse/
```

На целевом устройстве:

```bash
python3 -m pip install \
  --no-index \
  --find-links ./wheelhouse \
  -r offline-requirements.txt \
  --break-system-packages

cd nodrix
scripts/install_offline.sh -- --break-system-packages
```

Для Raspberry Pi зависимости следует скачивать на Linux ARM64 или использовать `pip download` с подходящими `--platform`, `--python-version` и `--abi`. Самый надёжный вариант — один раз дать плате интернет либо собрать wheel непосредственно на этой плате.

## Системные зависимости

Ubuntu/Raspberry Pi:

```bash
sudo apt install -y \
  build-essential \
  python3-dev \
  python3-venv \
  cmake \
  ffmpeg
```

Проверка:

```bash
nodrix --version
nodrix native doctor
nodrix media doctor
```
