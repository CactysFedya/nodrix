# Руководство: операции workspace

Создадим два контекста для одного проекта: локальную разработку и запуск на роботе.

## 1. Создайте workspace

```bash
mkdir robot-stack
cd robot-stack
plyctl workspace init .
```

## 2. Опишите проект

`nodrix.yaml`:

```yaml
schema: nodrix.project/v1
name: robot-stack

defaults:
  pipeline: diagnostics
  context: local
  view: compact

pipelines:
  diagnostics: pipelines/diagnostics.yaml

contexts:
  local:
    environment: local
    profile: default
    view: compact
  robot:
    environment: ros2
    profile: mid360s
    view: operations
```

## 3. Добавьте environments

`environments/local.yaml`:

```yaml
schema: nodrix.environment/v1
name: local
environment:
  LOG_LEVEL: debug
checks:
  - type: command
    command: python --version
```

`environments/ros2.yaml`:

```yaml
schema: nodrix.environment/v1
name: ros2
shell:
  source:
    - /opt/ros/jazzy/setup.bash
    - ${HOME}/livox_ws/install/setup.bash
environment:
  ROS_DISTRO: jazzy
  ROS_DOMAIN_ID: "26"
  ROS_AUTOMATIC_DISCOVERY_RANGE: SUBNET
checks:
  - type: file
    path: /opt/ros/jazzy/setup.bash
  - type: command
    command: ros2 --help
  - type: environment
    name: ROS_DISTRO
```

## 4. Добавьте profiles

`profiles/default.yaml`:

```yaml
schema: nodrix.profile/v1
name: default
runtime_profile: balanced
variables:
  DEVICE_KIND: laptop
```

`profiles/mid360s.yaml`:

```yaml
schema: nodrix.profile/v1
name: mid360s
runtime_profile: realtime-low-latency
variables:
  DEVICE_KIND: robot
  LIDAR_MODEL: MID360S
  FASTLIO_CONFIG_FILE: ${PROJECT_ROOT}/configs/fastlio2/mid360.yaml
```

## 5. Сравните контексты

```bash
plyctl context list
plyctl use local
plyctl workspace show
plyctl env check

plyctl use robot
plyctl workspace show
plyctl env show
plyctl env check
```

На ноутбуке локальная проверка должна пройти, а robot-контекст обязан явно показать отсутствие ROS 2 или Livox workspace.

## 6. Откройте подготовленный shell

```bash
plyctl shell
```

Shell подключает setup-скрипты, экспортирует переменные и показывает workspace/context в prompt.

## 7. Запустите фоновую эксплуатацию

```bash
plyctl prepare
plyctl up
plyctl ps
plyctl top
plyctl logs -f
```

Остановка:

```bash
plyctl down --timeout 10
```

Сначала отправляется `SIGINT`, затем при необходимости `SIGTERM` и `SIGKILL` всей группе процессов.
