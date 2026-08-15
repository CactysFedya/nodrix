# Интеграция ROS 2

Граница ответственности:

- DDS переносит ROS messages;
- Plyctl описывает и управляет operational graph;
- provider metadata объявляет applications, external ports, probes и requirements;
- sampled health и process metrics отображаются в `plyctl top`.

## Почему большие messages остаются в DDS

Передача point clouds, images и IMU через Python только ради orchestration добавляет latency и memory pressure. Если Plyctl node не обрабатывает payload, данные остаются в DDS, а runtime наблюдает rate, readiness и process health.

## Workspace environment

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
```

## Workflow

```bash
plyctl use robot
plyctl env check
plyctl prepare
plyctl validate PIPELINE
plyctl up PIPELINE
plyctl top
plyctl logs -f
```

ROS inspection в том же environment:

```bash
plyctl shell
ros2 node list
ros2 topic list
ros2 topic hz /topic
```

## External edges

Provider descriptor может объявлять external inputs/outputs. Manifest отражает ROS topic как внешний контракт, не притворяясь, что payload проходит через обычный in-process edge.

## Метрики процесса

Managed ROS 2 application должна учитывать process tree, а не только supervisor process. Operations view предназначен для PID, aggregate CPU/RAM, количества processes/threads и restarts.
