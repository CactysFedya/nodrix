# Nodrix spatial-semantic mapping roadmap

## Objective

Build a reusable Nodrix reference pipeline that consumes LiDAR, IMU and camera data, runs a replaceable visual-LiDAR-inertial odometry application, and produces:

1. an incremental metric 3D map;
2. a 2.5D traversability map and derived 2D navigation representation;
3. a persistent semantic/object map from detector observations.

FAST-LIVO2, YOLO, ROS 2, Livox and concrete map backends remain outside Core.

## Priority order

### Phase 1 — runtime correctness and data path

1. Existing #18: process-tree metrics and cleanup.
2. Existing #21: external-process provider adapter.
3. Event-time, timestamp and clock-domain contracts.
4. Bounded temporal join.
5. High-throughput image/point-cloud bridges with copy accounting.
6. Existing #43: performance baselines, promoted to P1.

### Phase 2 — spatial and mapping contracts

1. Versioned calibration artifacts and frame validation.
2. Incremental map tile/delta/revision/snapshot contracts.
3. Detection, 3D observation and persistent object-map contracts.
4. Existing #20: public Provider SDK and contract-test kit.

### Phase 3 — ROS 2 and reproducibility

1. TF2 event-time lookup and QoS validation, split from #47.
2. Existing #24: declared/observed DDS edges.
3. Existing #25: topic health, skew metrics and rosbag operations.
4. Pin and qualify an exact FAST-LIVO2 ROS 2 implementation.
5. Existing #44: built-artifact and bag-replay smoke tests.
6. Existing #45: evidence-based support matrix.

### Phase 4 — implementation providers and vertical slice

1. Reference incremental metric 3D map provider.
2. 2.5D elevation/traversability provider and 2D navigation projection.
3. Detector/tracker provider with a YOLO reference backend.
4. Event-time 2D-to-3D observation fusion and persistent object-map provider.
5. rosbag integration: LiDAR + IMU + camera + TF.
6. FAST-LIVO2: odometry + registered point cloud.
7. Compose all outputs into one headless/RViz/replay integration.
8. Live hardware qualification after replay is stable.

## Milestones

- `2.3.0b1`: stabilization, smoke tests and performance regression foundations.
- `2.4.0`: universal provider, temporal, spatial, mapping and semantic contracts.
- `2.5.0`: ROS 2 graph/TF/QoS/rosbag semantics and qualified FAST-LIVO2 integration.

## Script behavior

`nodrix_mapping_issues_setup.sh`:

- verifies GitHub CLI authentication;
- creates four missing area labels;
- updates #20, #21, #25, #43, #44 and #47;
- promotes #43 from P2 to P1;
- splits TF2/QoS work from #47;
- creates one epic and thirteen new issues without duplicating exact titles;
- attempts to add dependency and sub-issue relationships;
- assigns milestones, labels and the current GitHub user;
- prints the resulting issue numbers.

## Run

```bash
cd /path/to/nodrix
chmod +x nodrix_mapping_issues_setup.sh
gh auth status
./nodrix_mapping_issues_setup.sh
```

To target another repository or assignee:

```bash
REPO=owner/repository ASSIGNEE=github-login ./nodrix_mapping_issues_setup.sh
```

## Review after creation

```bash
gh issue list --milestone 2.4.0 --state open
gh issue list --milestone 2.5.0 --state open
gh issue list --label "area: mapping" --state open
gh issue list --label "area: semantic" --state open
```
