# Raspberry Pi 5 Mapping Reference System — M4

M4 is the first end-to-end dogfood system for the 2.7 architecture.

## Runtime path

```text
Livox MID-360S
  -> livox_ros_driver2
  -> FAST-LIO2
  -> /cloud_registered (sensor_msgs/msg/PointCloud2)
  -> ros2.point_cloud2_source
  -> spatial.point_cloud/v1
  -> mapping.voxel_map (C++20)
  -> mapping.voxel_snapshot/v1
  -> mapping.ply_store
  -> artifacts/maps/metric/latest.ply
```

External ROS 2 software remains an Application. The point-cloud bridge and
mapping data plane are Nodrix Nodes. The ROS environment is one shared
ResourceInstance.

`plyctl prepare` is the only source-acquisition phase. `system run` never
clones, installs, or builds. Existing repositories are reused and are not
updated unless `--refresh` is explicitly requested by the source helper.

Pinned defaults:
- Livox-SDK2 `v1.3.1`
- livox_ros_driver2 `1.2.6`
- FAST_LIO_ROS2 `ros2`

Resolved SHAs are recorded in `.nodrix/reference-sources.json`.

Livox ROS Driver 2 uses ROS-specific package/launch source files. Prepare
normalizes them once and Nodrix then uses ordinary `ros2.colcon`, avoiding the
upstream build script's destructive build/install cleanup.

Livox-SDK2 installs under `.nodrix/prefix/livox-sdk2`. ROS session environment
values resolve `${PROJECT_ROOT}`, so `LD_LIBRARY_PATH` can reference the
project-local SDK instead of requiring `/usr/local`.

## Raspberry Pi 5 flow

```text
plyctl use rpi5-mapping
plyctl prepare
plyctl build --plan
plyctl build
plyctl test
plyctl system validate
plyctl system plan
plyctl system run
```

The reference System uses ROS_DOMAIN_ID=26 and `msg_MID360s_launch.py`.

FAST_LIO_ROS2's `ros2` branch contains `config/mid360.yaml`. Upstream does not
promise ROS 2 Jazzy compatibility and has an open Jazzy issue, so this
combination remains a qualification target until it is proven on the robot.

The upstream `mid360.yaml` enables online LiDAR/IMU extrinsic estimation.
Robot-specific calibration and timing still require qualification before
production use.
