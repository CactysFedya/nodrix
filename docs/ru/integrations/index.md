# Интеграции

## ROS 2

ROS 2 реализуется отдельными пакетами и провайдерами. Core остаётся независимым
от `rclpy`, DDS и конкретного дистрибутива ROS 2.

```yaml
applications:
  driver:
    uses: ros2.launch
    bindings: {session: ros}
    package: example_driver
    launch_file: driver.launch.py
nodes: {}
edges:
  - from: driver.points
    to: mapping.points
    transport:
      uses: ros2.topic
      parameters:
        topic: /points
        message_type: sensor_msgs/msg/PointCloud2
```

## Другие направления

Та же модель применяется для Media, Vision, Mapping, сенсоров, внешних
процессов и будущих протоколов вроде MQTT: интеграция добавляет провайдеры и
контракты, но не меняет ядро pipeline.
