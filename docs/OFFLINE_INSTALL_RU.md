# Офлайн-установка Nodrix 1.1.0

Nodrix 1.1.0 снижает минимальное требование build backend до `setuptools>=68` и не требует `packaging>=24.2` только для чтения лицензии. Это позволяет собирать проект на Ubuntu 24.04/Raspberry Pi без обращения к PyPI, если основные зависимости уже перенесены локально.

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

Скрипт сначала проверяет локальное наличие `setuptools`, `wheel`, `typer`, `pydantic`, `PyYAML` и `rich`, затем компилирует четыре C++-расширения без сетевых запросов.

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
nodrix media doctor
```
