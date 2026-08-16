# FAST-LIVO2 semantic mapping reference integration

This integration is a hardware dogfooding scenario for the generic Plyctl
model. FAST-LIVO2, Livox, ROS 2, Vision, and semantic mapping remain outside
Core.

## Data flow

```text
Livox LiDAR + IMU ──► FAST-LIVO2 ──► registered cloud + odometry + map
RTSP camera ─────────► NCNN YOLO ──► realtime tracker
                                   │
cloud + odometry + calibration + tracks
                                   ▼
                          2D-to-3D fusion
                                   ▼
                     tracked objects + object map
```

## Observed ROS 2 topics

Inputs and metric outputs include:

```text
/livox/lidar
/livox/imu
/cloud_registered
/aft_mapped_to_init
/Laser_map
/path
/rgb_img
```

Semantic visualization outputs:

```text
/semantic/object_points
/semantic/object_centers
```

Both semantic topics use `sensor_msgs/msg/PointCloud2`. RViz subscribers must
use a compatible reliability policy.

## Persistent artifacts

```text
artifacts/maps/metric/latest.ply
artifacts/maps/semantic/objects.sqlite
artifacts/maps/semantic/objects.json
```

`latest.ply` and `objects.json` are current snapshots. SQLite is the updateable
object store.

## Qualification state

Confirmed:

- Pipeline applications and nodes can reach ready state on Raspberry Pi 5.
- FAST-LIVO2 publishes registered cloud, odometry, path, image, and map
  endpoints.
- Semantic ROS publishers and semantic storage files are created.
- Remote RViz can display metric and diagnostic topics.

Not yet confirmed:

- Correct, non-empty semantic point output.
- Valid 3D object association against ground truth.
- Persistent `latest.ply` creation for a received `/Laser_map` message.
- Long-duration restart, recovery, and shutdown behavior.
- Absence of duplicate Livox driver processes.

## Architectural boundary

The reference project may contain calibration, ROS bringup packages,
thresholds, and hardware profiles. None of these are Core defaults. Generic
spatial and semantic contracts must be versioned provider contracts before
this example can be called production-qualified.

## Canonical storage semantics

The paths `artifacts/maps/metric/latest.ply`,
`artifacts/maps/semantic/objects.sqlite`, and
`artifacts/maps/semantic/objects.json` are domain-facing mutable snapshots.
They are not canonical immutable Artifact revision identity.

When a snapshot is preserved as a canonical Nodrix Artifact revision, its
content is materialized independently through the Canonical Storage Standard
under the immutable revision layout in `artifacts/`. Updating `latest.ply`
therefore does not overwrite or change previously materialized revisions.
