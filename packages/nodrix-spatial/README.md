# nodrix-spatial

Transport-neutral spatial contracts for Nodrix.

The package owns point clouds, IMU samples, poses, odometry and transforms. It
contains no ROS 2, mapping, PCL or sensor-driver implementation. Large point
cloud payloads are backed by `ManagedBuffer` and are not converted to Python
lists.

User-facing pipelines may use short aliases such as `spatial.point_cloud`.
Provider metadata keeps the canonical versioned contract
`spatial.point_cloud/v1` for compatibility checks and lock files.
