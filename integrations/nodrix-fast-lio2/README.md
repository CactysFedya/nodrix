
# Nodrix FAST-LIO2 integration

```text
Livox MID-360S → FAST-LIO2 → RViz
```

Large ROS messages remain inside DDS. Plyctl manages process lifecycle,
readiness, restarts, logs and health.

## Environment

```bash
export ROS_DISTRO=jazzy
export ROS_DOMAIN_ID=26
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
export ROBOT_WS=$HOME/livox_ws
export FASTLIO_CONFIG_FILE=mid360s_handheld.yaml
```

## Normal run

```bash
plyctl validate \
  integrations/nodrix-fast-lio2/pipelines/orchestrated-ros2.yaml

plyctl run \
  integrations/nodrix-fast-lio2/pipelines/orchestrated-ros2.yaml
```

Startup ordering uses ROS 2 graph and message-type contracts from the
`ros2.topic` edges. Large sensor streams are not deserialized by Plyctl in
the critical startup path.

## Diagnostic sampled run

```bash
plyctl run \
  integrations/nodrix-fast-lio2/pipelines/diagnostic-sampled.yaml
```

The diagnostic pipeline continuously checks:

- `/livox/lidar` at at least 8 Hz;
- `/livox/imu` at at least 150 Hz;
- `/cloud_registered` at at least 8 Hz.

This mode adds Python deserialization overhead.

Diagnostic monitors do not gate application startup. A slow Python diagnostic
subscriber may observe fewer messages than native ROS 2 consumers, so its
reported rate must not be used to block FAST-LIO2 or RViz.
