# Установка

Для Plyctl 2.3 требуется Python 3.11 или новее. Для разработки и CI рекомендуется Python 3.12.

## Установка именно документируемой ветки

```bash
git clone https://github.com/CactysFedya/nodrix.git
cd nodrix
git switch feature/2.3.0-workspace-and-operations

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Проверка:

```bash
plyctl --version
plyctl --help
python -c "import plyctl; print(plyctl.__version__)"
```

Ожидаемая версия:

```text
2.3.0a1
```

## Дополнительные возможности

Устанавливайте только необходимые extra-зависимости:

```bash
python -m pip install -e '.[docs]'
python -m pip install -e '.[dev]'
python -m pip install -e '.[vision,media,viewer]'
```

Точные имена extra смотрите в `pyproject.toml` текущей ветки.

## Хост с ROS 2

Сам Plyctl устанавливается в обычное Python-окружение. ROS 2 setup-файлы лучше подключать через `environments/*.yaml`, а не вручную в каждом терминале:

```text
/opt/ros/jazzy/setup.bash
$HOME/livox_ws/install/setup.bash
```

## Частые проблемы

### Команда `plyctl` не найдена

```bash
which python
python -m pip show plyctl
python -m plyctl.cli --help
```

### Видна старая команда `nodrix`

Это нормальная совместимость серии 2.x. В новых сценариях используйте `plyctl`.

### Установка зависает

Проверьте DNS, proxy и доступ к package index. Для обычного редактирования Markdown локальная установка Sphinx не нужна: обе языковые версии собирает GitHub Actions.
