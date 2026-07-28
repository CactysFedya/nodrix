# Установка Nodrix 1.1.0

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install "nodrix[media,viewer]==1.1.0"
```

Локальный release-файл:

```bash
pip install nodrix-1.1.0.tar.gz
```

Проверка:

```bash
nodrix --version
nodrix data-plane doctor
nodrix device doctor
nodrix media doctor
nodrix-viewer --help
```

Устанавливаются только команды `nodrix` и `nodrix-viewer`. Старые `vpipe` и `visionpipe` не поддерживаются.

Python-граф не требует сборки. Исходный пакет компилирует нативные расширения при установке, поэтому для него нужны C++20 toolchain и Python headers.

## Офлайн-сборка

```bash
pip install . --no-build-isolation --no-deps
```

Минимальный build backend: `setuptools>=68`.
