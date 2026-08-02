# Nodrix ROS 2 project

This generic example supervises the standard ROS 2 C++ talker and listener as
managed Applications. The message remains in DDS/RMW; the logical Edge carries
a `ros2.topic` Transport and does not copy payloads through Python.

On Ubuntu 24.04 with ROS 2 Jazzy:

```bash
sudo apt install ros-jazzy-demo-nodes-cpp
source /opt/ros/jazzy/setup.bash
nodrix validate pipeline.yaml
nodrix run pipeline.yaml
```

Replace the two Applications with an existing driver, launch file, SLAM
system, or visualizer. Add a workspace path and change the session build mode
to `if-needed` only when the project owns a colcon overlay.
