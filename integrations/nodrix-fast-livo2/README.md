# FAST-LIVO2 → Nodrix integration

FAST-LIVO2 remains an external ROS 2 process. This integration validates and
consumes its registered point cloud and odometry topics.

## Expected topics

```text
/cloud_registered  sensor_msgs/msg/PointCloud2
/odometry          nav_msgs/msg/Odometry
```

Topic names can be overridden directly in the pipeline.

## Run

```bash
source /opt/ros/${ROS_DISTRO:-jazzy}/setup.bash
python -m pip install -e packages/nodrix-mapping
python -m pip install -e packages/nodrix-ros2

nodrix provider list
nodrix doctor --provider nodrix.ros2 --deep
nodrix validate integrations/nodrix-fast-livo2/pipelines/input.yaml
nodrix run integrations/nodrix-fast-livo2/pipelines/input.yaml
```
