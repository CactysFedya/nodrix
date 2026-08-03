# Nodrix Workspace 2.3

Nodrix Workspace отделяет код ядра от пользовательского проекта.

## Минимальная структура

```text
project/
├── nodrix.yaml
├── pipelines/
├── configs/
├── environments/
├── profiles/
├── views/
└── .nodrix/
```

`nodrix.yaml` хранит алиасы pipeline, контексты и значения по умолчанию.
Nodrix ищет этот файл вверх по дереву каталогов.

## Ежедневная работа

```bash
cd project
plyctl use robot
plyctl prepare
plyctl run
```

Для фоновой эксплуатации:

```bash
plyctl up
plyctl ps
plyctl top
plyctl logs -f
plyctl down
```

Для ручной диагностики в том же окружении:

```bash
plyctl shell
```

## Контекст

Контекст объединяет environment, profile и view:

```yaml
contexts:
  robot:
    environment: ros2
    profile: mid360s
    view: operations
```

## Environment

Environment хранит setup scripts, переменные и preflight-проверки:

```yaml
schema: nodrix.environment/v1
name: ros2
shell:
  source:
    - /opt/ros/jazzy/setup.bash
    - ${HOME}/livox_ws/install/setup.bash
environment:
  ROS_DOMAIN_ID: "26"
  ROS_AUTOMATIC_DISCOVERY_RANGE: SUBNET
checks:
  - type: file
    path: /opt/ros/jazzy/setup.bash
  - type: command
    command: ros2 --help
```

## View

Встроенные представления `plyctl top`:

- `compact` — вывод без внешних рамок;
- `operations` — PID, процессы, потоки и рестарты;
- `debug` — полный старый диагностический dashboard.
