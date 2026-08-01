# Nodrix 2.2.0-alpha.2 — ROS 2 Orchestrator Foundation

This increment turns `nodrix-ros2` from a transport-only alpha into a generic
ROS 2 orchestration provider while preserving the normal Nodrix
`nodes + edges` pipeline model.

## Added

- independent `nodrix-spatial 0.1.0` package;
- canonical PointCloud, IMU, Odometry and Transform contracts;
- `nodrix-ros2 0.2.0` without a dependency on Mapping;
- `ros2.node`, `ros2.launch` and `ros2.rviz` process nodes;
- process-group lifecycle: SIGINT, SIGTERM, SIGKILL fallback;
- ROS underlay/overlay environment capture;
- automatic `colcon build --symlink-install` in `if-needed` mode;
- deterministic workspace source fingerprint and build cache;
- ROS topic prerequisites before launching dependent applications;
- `ros2.topic_monitor` for startup readiness, rate and staleness;
- typed `sensor_msgs/msg/Imu` source;
- a full Livox → FAST-LIVO2 → RViz orchestration example.

## Package boundaries

```text
nodrix
├── nodrix-spatial        transport-neutral spatial payloads
├── nodrix-mapping        map domain + temporary alpha aliases
└── nodrix-ros2           ROS platform, workspace and supervision
```

`nodrix-ros2` contains no Livox, FAST-LIVO2, mapping or camera algorithm. Those
systems are described through generic ROS nodes and catalog/application YAML.

## Performance rule

ROS-to-ROS flows remain entirely in ROS 2 DDS/RMW:

```text
Livox C++ → ROS 2 → FAST-LIVO2 C++ → RViz
```

Python participates only in the control plane. Large data enters the Nodrix
runtime only through an explicit typed bridge such as
`ros2.point_cloud2_source`.

## Validation performed without a ROS installation

- 15 package tests passed using public Nodrix API stubs;
- all Python modules compiled;
- independent wheels built for `nodrix-spatial`, `nodrix-mapping` and
  `nodrix-ros2`;
- PointCloud adapter retains the ROS data buffer owner without adapter-level
  copying;
- managed process-group shutdown was tested.

Real ROS 2 graph, QoS and hardware validation remains required on Ubuntu 24.04
with ROS 2 Jazzy.
