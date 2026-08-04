# Руководство: запуск ROS 2 и FAST-LIO2

Большие ROS-сообщения остаются в DDS, а Plyctl управляет lifecycle, readiness, restart, logs, health и ресурсами процессов.

```text
Livox driver ── DDS ──> FAST-LIO2 ── DDS ──> RViz
      │                     │
      └──── управление и наблюдение ───── Plyctl
```

## 1. Проверьте хост

```bash
test -f /opt/ros/jazzy/setup.bash
test -f "$HOME/livox_ws/install/setup.bash"
ros2 --help
```

## 2. Выберите robot context

```bash
plyctl context list
plyctl use robot
plyctl workspace show
plyctl env check
```

В workspace ветки есть aliases `fastlio2` и `fastlio2-rviz`, ROS 2 environment, профиль MID-360S и operations view.

## 3. Проверьте переменные

```bash
plyctl env show
plyctl env export
```

Проверьте `ROS_DISTRO`, `ROS_DOMAIN_ID`, `ROS_AUTOMATIC_DISCOVERY_RANGE` и `FASTLIO_CONFIG_FILE`.

## 4. Статическая проверка

```bash
plyctl prepare
plyctl validate fastlio2
plyctl inspect fastlio2
```

Manifest validation не заменяет проверку реального LiDAR, но заранее ловит ошибки конфигурации и provider descriptors.

## 5. Запуск

```bash
plyctl up fastlio2
plyctl ps
plyctl top
plyctl logs -f
```

С RViz:

```bash
plyctl restart fastlio2-rviz
```

## 6. Проверка DDS

```bash
plyctl shell
ros2 node list
ros2 topic list
ros2 topic hz /livox/lidar
ros2 topic hz /livox/imu
ros2 topic hz /cloud_registered
```

Примерные health thresholds интеграции: LiDAR 8 Гц, IMU 150 Гц, registered cloud 8 Гц. Их необходимо настроить по фактической конфигурации.

## 7. Остановка

```bash
plyctl down --timeout 15
plyctl ps
plyctl logs -n 200
```
