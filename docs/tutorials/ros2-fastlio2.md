# Tutorial: run ROS 2 and FAST-LIO2

This tutorial uses the workspace and managed-application layers rather than moving large ROS messages through Python.

## Architecture

```text
Livox driver ── DDS ──> FAST-LIO2 ── DDS ──> RViz / downstream nodes
      │                     │
      └──── lifecycle, health, logs, metrics ──── Plyctl
```

Point clouds and IMU samples remain in ROS 2 DDS. Plyctl manages launch order, readiness, restarts, logs, sampled health, and resource reporting.

## 1. Prepare the host

Confirm the setup scripts exist:

```bash
test -f /opt/ros/jazzy/setup.bash
test -f "$HOME/livox_ws/install/setup.bash"
ros2 --help
```

## 2. Select the robot context

From the repository workspace:

```bash
plyctl context list
plyctl use robot
plyctl workspace show
plyctl env check
```

The branch workspace maps aliases such as `fastlio2` and `fastlio2-rviz` to integration pipelines and applies the ROS 2 environment, MID-360S profile, and operations view.

## 3. Inspect the resolved environment

```bash
plyctl env show
plyctl env export
```

Verify at least:

```text
ROS_DISTRO=jazzy
ROS_DOMAIN_ID=26
ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
FASTLIO_CONFIG_FILE=...
```

## 4. Validate before touching hardware

```bash
plyctl prepare
plyctl validate fastlio2
plyctl inspect fastlio2
```

Validation catches missing node descriptors and manifest errors. Environment checks catch missing setup files and commands. Hardware connectivity is still a runtime concern.

## 5. Launch

Foreground:

```bash
plyctl run fastlio2
```

Background operation:

```bash
plyctl up fastlio2
plyctl ps
plyctl top
plyctl logs -f
```

With RViz when the alias exists:

```bash
plyctl restart fastlio2-rviz
```

## 6. Verify ROS 2 externally

Use the same resolved shell:

```bash
plyctl shell
ros2 node list
ros2 topic list
ros2 topic hz /livox/lidar
ros2 topic hz /livox/imu
ros2 topic hz /cloud_registered
```

The integration health model samples expected rates around 8 Hz for LiDAR, 150 Hz for IMU, and 8 Hz for registered clouds. Tune thresholds to the actual driver and hardware configuration rather than treating these examples as universal constants.

## 7. Stop cleanly

```bash
plyctl down --timeout 15
```

Check that managed child processes are gone and inspect the final log tail:

```bash
plyctl ps
plyctl logs -n 200
```
