# nodrix-mapping

Mapping-domain package for Nodrix.

Version 0.1.1 keeps the alpha compatibility aliases
`mapping.point_cloud/v1` and `geometry.odometry/v1`, while the owning contracts
now live in `nodrix-spatial` as `spatial.point_cloud/v1` and
`spatial.odometry/v1`. New code must depend on `nodrix-spatial` directly.

Mapping algorithms and map payloads will be added here without adding sensor or
ROS 2 knowledge to the package.
