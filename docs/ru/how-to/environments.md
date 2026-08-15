# Окружения, профили и контексты

## Host setup храните в environment

```yaml
schema: nodrix.environment/v1
name: ros2
shell:
  source:
    - /opt/ros/jazzy/setup.bash
    - ${HOME}/robot_ws/install/setup.bash
environment:
  ROS_DOMAIN_ID: "26"
  ROS_AUTOMATIC_DISCOVERY_RANGE: SUBNET
checks:
  - type: file
    path: /opt/ros/jazzy/setup.bash
  - type: directory
    path: ${HOME}/robot_ws/install
  - type: command
    command: ros2 --help
  - type: environment
    name: ROS_DISTRO
```

В 2.3 поддерживаются проверки `file`, `directory`, `command`, `environment`.

## Hardware и tuning храните в profile

```yaml
schema: nodrix.profile/v1
name: mid360s
runtime_profile: realtime-low-latency
variables:
  SENSOR_MODEL: MID360S
  CONFIG_ROOT: ${PROJECT_ROOT}/configs
  FASTLIO_CONFIG_FILE: ${CONFIG_ROOT}/fastlio2/mid360.yaml
```

## Объедините их context

```yaml
contexts:
  robot:
    environment: ros2
    profile: mid360s
    view: operations
```

## Приоритет переменных

Порядок слияния:

1. `environment.environment`;
2. `profile.variables`;
3. `context.variables`.

Поздний слой переопределяет ранний. Доступны `${PROJECT_ROOT}`, `${HOME}` и ранее разрешённые переменные.

## Экспорт

```bash
plyctl use robot
plyctl env export > /tmp/robot-env.sh
source /tmp/robot-env.sh
```

Для интерактивной работы предпочтительнее `plyctl shell`, потому что он также подключает setup-скрипты.
