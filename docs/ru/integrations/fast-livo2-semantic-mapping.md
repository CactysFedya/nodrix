# Reference integration FAST-LIVO2 и semantic mapping

Эта интеграция является hardware dogfooding-сценарием универсальной модели
Plyctl. FAST-LIVO2, Livox, ROS 2, Vision и semantic mapping остаются за
границей Core.

## Поток данных

```text
Livox LiDAR + IMU ──► FAST-LIVO2 ──► registered cloud + odometry + map
RTSP camera ─────────► NCNN YOLO ──► realtime tracker
                                   │
cloud + odometry + calibration + tracks
                                   ▼
                          2D-to-3D fusion
                                   ▼
                     tracked objects + object map
```

## Наблюдаемые ROS 2 topics

```text
/livox/lidar
/livox/imu
/cloud_registered
/aft_mapped_to_init
/Laser_map
/path
/rgb_img
/semantic/object_points
/semantic/object_centers
```

Оба semantic topic используют `sensor_msgs/msg/PointCloud2`. В RViz
необходимо выбирать совместимую reliability policy.

## Сохраняемые artifacts

```text
artifacts/maps/metric/latest.ply
artifacts/maps/semantic/objects.sqlite
artifacts/maps/semantic/objects.json
```

`latest.ply` и `objects.json` являются актуальными snapshots. SQLite является
обновляемым object store.

## Состояние qualification

Подтверждено:

- Applications и nodes доходят до ready на Raspberry Pi 5.
- FAST-LIVO2 создаёт endpoints registered cloud, odometry, path, image и map.
- Создаются semantic ROS publishers и файлы semantic storage.
- Удалённый RViz отображает metric и diagnostic topics.

Ещё не подтверждено:

- Корректный ненулевой semantic point output.
- Правильная 3D association объектов относительно ground truth.
- Создание `latest.ply` после фактического сообщения `/Laser_map`.
- Длительная работа, recovery и shutdown.
- Отсутствие нескольких одновременно запущенных Livox drivers.

## Архитектурная граница

Reference project может содержать calibration, ROS bringup packages,
thresholds и hardware profiles. Они не являются Core defaults. Generic spatial
и semantic contracts должны стать версированными provider contracts до
объявления интеграции production-qualified.
