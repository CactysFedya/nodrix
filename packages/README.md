# Nodrix package workspace

This directory contains independently installable Nodrix distributions.

```bash
python -m pip install -e packages/nodrix-mapping
python -m pip install -e packages/nodrix-ros2
```

ROS 2 itself is intentionally not installed through PyPI. Source the required
ROS distribution before running a ROS-backed pipeline.
