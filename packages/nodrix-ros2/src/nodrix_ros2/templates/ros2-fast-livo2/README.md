# Nodrix ROS 2 project

This project keeps the usual compact Nodrix YAML shape and adds one shared
`ros2.session`. The workspace is sourced and, when necessary, built once per
pipeline. ROS-to-ROS payloads remain in DDS; `links` describe readiness and
remapping without copying point clouds through Python.

Copy `.env.example` to `.env`, export the variables, then run:

```bash
nodrix validate pipeline.yaml
nodrix run pipeline.yaml
```

Use `mode: graph` for cheap topic readiness checks. Change an individual
monitor to `mode: sample` only when Nodrix must measure message arrival rate.
