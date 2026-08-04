# ROS 2 integration

The ROS 2 integration is designed around a clear boundary:

- DDS transports ROS messages between ROS 2 processes;
- Plyctl describes and supervises the operational graph;
- provider metadata exposes managed applications, external ports, probes, and requirements;
- sampled health and process metrics are shown in `plyctl top`.

## Why large messages stay in DDS

Copying point clouds, images, and IMU streams through Python solely for orchestration adds latency and memory pressure. When no Plyctl node needs the payload, the integration leaves data in DDS and observes rates, readiness, and process health instead.

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

## Operational workflow

```bash
plyctl use robot
plyctl env check
plyctl prepare
plyctl validate PIPELINE
plyctl up PIPELINE
plyctl top
plyctl logs -f
```

For native ROS inspection inside the same environment:

```bash
plyctl shell
ros2 node list
ros2 topic list
ros2 topic hz /topic
```

## External edges and validation

Provider descriptors can declare external inputs and outputs. This lets the manifest represent a connection to a ROS topic without pretending that the payload crosses a normal in-process edge. Validation can then reason about the declared external contract while runtime health checks observe the actual DDS graph.

## Resource metrics

Managed ROS 2 applications should report the process tree, not only the supervisor process. The operations view is intended to expose PID, aggregate CPU and memory, process/thread counts, and restart information.
