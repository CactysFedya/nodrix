# FAST-LIO2 integration

The 2.3 branch includes FAST-LIO2 integration as managed ROS 2 applications and workspace aliases.

## Data path

Typical topics:

```text
Livox driver
├── LiDAR points  → FAST-LIO2
└── IMU           → FAST-LIO2

FAST-LIO2
├── registered point cloud
├── odometry
└── TF
```

Plyctl handles launch order, setup environment, process lifecycle, readiness, restart policy, logs, sampled topic health, and resource metrics. It does not replace FAST-LIO2 or DDS.

## Branch workspace aliases

The repository workspace includes aliases such as:

```yaml
pipelines:
  fastlio2: ...
  fastlio2-rviz: ...
```

Inspect the exact resolved paths in the checked-out branch:

```bash
plyctl workspace show
plyctl inspect fastlio2
plyctl inspect fastlio2-rviz
```

## Expected health samples

The integration documentation and tests use representative expectations near:

- LiDAR: 8 Hz;
- IMU: 150 Hz;
- registered cloud: 8 Hz.

These are deployment defaults, not algorithm invariants. Set thresholds from measured sensor configuration and desired failure detection time.

## Startup checklist

```bash
plyctl use robot
plyctl env check
plyctl prepare
plyctl up fastlio2
plyctl logs -f
```

Then verify:

```bash
plyctl shell
ros2 topic hz /livox/lidar
ros2 topic hz /livox/imu
ros2 topic hz /cloud_registered
```

## RViz

Use the `fastlio2-rviz` alias when the branch configuration includes it. RViz still subscribes to ROS 2 topics directly; Plyctl only manages its process and operational status.
