# ROS 2 integration

Install the core orchestrator first. Add spatial bridges only when a Plyctl
algorithm needs typed PointCloud2, IMU, or Odometry payloads.

```bash
python -m pip install plyctl plyctl-ros2
python -m pip install plyctl-spatial plyctl-spatial-ros2  # optional
```

ROS 2 remains installed and managed by the operating system. Plyctl discovers
the ROS environment, sources underlays, fingerprints a colcon workspace,
builds it in `if-needed` mode, waits for required topics, supervises process
groups, and writes a separate stdout/stderr log for every process.

## FAST-LIVO2 example

```bash
export LIVOX_WS=/path/to/livox_ws/install
export ROBOT_WS=/path/to/robot_ws
plyctl validate integrations/nodrix-fast-livo2/pipelines/orchestrated-ros2.yaml
plyctl run integrations/nodrix-fast-livo2/pipelines/orchestrated-ros2.yaml
```

The graph is:

```{mermaid}
flowchart LR
  Livox["Livox driver"] --> Topics["/livox/lidar + /livox/imu"]
  Topics --> Fast["FAST-LIVO2"]
  Fast --> Cloud["/cloud_registered"]
  Cloud --> RViz["RViz"]
```

The driver and FAST-LIVO2 remain ordinary ROS 2 packages. No
algorithm-specific Plyctl plugin is required. RViz may run on the robot, or on
a laptop in the same correctly configured ROS 2 DDS domain; network discovery,
firewall, `ROS_DOMAIN_ID`, and middleware settings must match.

Create a generic ROS 2 project with:

```bash
plyctl init my-robot --template ros2
```
