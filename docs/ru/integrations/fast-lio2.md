# Интеграция FAST-LIO2

Ветка 2.3 содержит FAST-LIO2 как managed ROS 2 applications и workspace aliases.

## Data path

```text
Livox driver
├── LiDAR points  → FAST-LIO2
└── IMU           → FAST-LIO2

FAST-LIO2
├── registered cloud
├── odometry
└── TF
```

Plyctl управляет launch order, environment, lifecycle, readiness, restart policy, logs, sampled topic health и resource metrics. Он не заменяет FAST-LIO2 или DDS.

## Aliases

В repository workspace есть aliases вида:

```yaml
pipelines:
  fastlio2: ...
  fastlio2-rviz: ...
```

Проверяйте фактические paths:

```bash
plyctl workspace show
plyctl inspect fastlio2
plyctl inspect fastlio2-rviz
```

## Health defaults

Примерные ожидания интеграции:

- LiDAR — 8 Гц;
- IMU — 150 Гц;
- registered cloud — 8 Гц.

Это deployment defaults, а не неизменные свойства алгоритма.

## Запуск

```bash
plyctl use robot
plyctl env check
plyctl prepare
plyctl up fastlio2
plyctl logs -f
```

Проверка:

```bash
plyctl shell
ros2 topic hz /livox/lidar
ros2 topic hz /livox/imu
ros2 topic hz /cloud_registered
```

RViz подписывается на ROS 2 topics напрямую; Plyctl управляет только process и operational status.
