# FAST-LIVO2 → Plyctl integration

FAST-LIVO2 remains an external ROS 2 process. No algorithm-specific Python
plugin is required, and large sensor payloads stay in DDS/RMW unless an explicit
typed bridge is added.

Three pipeline modes are included:

- `pipelines/input.yaml` — consume an already running FAST-LIVO2 graph;
- `pipelines/orchestrated-ros2.yaml` — start a deployment-selected Livox driver,
  FAST-LIVO2 and RViz;
- `pipelines/replay-ros2.yaml` — replay a reference rosbag through a pinned
  FAST-LIVO2 ROS 2 candidate and monitor its required inputs and outputs.

## Qualified candidate

The first qualification candidate is `v4rl-ucy/FAST-LIVO2-ROS2`. The upstream
documentation targets Ubuntu 22.04 and ROS 2 Humble. Ubuntu 24.04 with ROS 2
Jazzy remains experimental until build, replay, cleanup and performance evidence
is recorded in `deployment/fast-livo2.lock.yaml`.

The deployment metadata is deliberately versioned separately from the generic
Nodrix providers:

```text
deployment/fast-livo2.lock.yaml    source revision, package, launch and evidence
deployment/reference-contract.yaml exact input/output topics and replay policy
deployment/supported-platforms.yaml qualification status by platform
```

The selected implementation is GPL-2.0-only. Review upstream licensing before
redistribution or commercial deployment.

## Reference contract

The MID-360/Fisheye compressed-image profile uses:

```text
/livox/lidar        livox_ros_driver2/msg/CustomMsg
/livox/imu          sensor_msgs/msg/Imu
/camera/left/jpeg   sensor_msgs/msg/CompressedImage
/cloud_registered   sensor_msgs/msg/PointCloud2
/Laser_map          sensor_msgs/msg/PointCloud2
/aft_mapped_to_init nav_msgs/msg/Odometry
/path                nav_msgs/msg/Path
```

These names are implementation-specific deployment facts, not universal Nodrix
core contracts. A different FAST-LIVO2 port or camera transport must use another
versioned reference profile.

## Static validation and source pinning

The helper only needs Python, Git and PyYAML; it does not import ROS:

```bash
python integrations/nodrix-fast-livo2/scripts/fast_livo2_deployment.py \
  validate --allow-unpinned

python integrations/nodrix-fast-livo2/scripts/fast_livo2_deployment.py pin

python integrations/nodrix-fast-livo2/scripts/fast_livo2_deployment.py validate

python -m pytest \
  integrations/nodrix-fast-livo2/tests/test_fast_livo2_deployment.py -q
```

`pin` resolves `refs/heads/main` with `git ls-remote` and writes the exact
40-character commit to the lock file. Run it before committing the integration;
production validation rejects an unresolved revision.

## Reference bag check

Before starting the pipeline, verify that the bag contains the exact required
input topics and message types:

```bash
export FAST_LIVO2_BAG=/absolute/path/to/reference-bag

python integrations/nodrix-fast-livo2/scripts/fast_livo2_deployment.py \
  bag-check --bag "$FAST_LIVO2_BAG"
```

For a bag directory, the command reads `metadata.yaml` directly. Otherwise it
uses `ros2 bag info --yaml`.

## Development install

```bash
python -m pip install -e packages/nodrix-spatial --no-deps
python -m pip install -e packages/nodrix-mapping --no-deps
python -m pip install -e packages/nodrix-ros2 --no-deps
python -m pip install -e packages/nodrix-spatial-ros2 --no-deps  # typed bridges only
```

## Replay

Prepare a workspace containing the pinned `fast_livo` package and a Livox driver
underlay, then run:

```bash
export ROS_DISTRO=humble
export LIVOX_WS=$HOME/livox_ws
export FAST_LIVO2_WS=$HOME/fast_livo2_ws
export FAST_LIVO2_BAG=/absolute/path/to/reference-bag

plyctl validate integrations/nodrix-fast-livo2/pipelines/replay-ros2.yaml
plyctl plan integrations/nodrix-fast-livo2/pipelines/replay-ros2.yaml
plyctl run integrations/nodrix-fast-livo2/pipelines/replay-ros2.yaml
```

The replay uses the native C++ `rosbag2_transport/player`, publishes `/clock`,
keeps loaned-message playback enabled and delays messages for 10 seconds. During
that delay the typed ROS graph edges allow FAST-LIVO2 to start and subscribe, so
the beginning of the bag is not intentionally discarded.

The topic monitors use graph mode. They validate publisher presence and message
type without deserializing PointCloud2 or camera payloads merely for readiness.
