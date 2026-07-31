# Nodrix 2.2.0-alpha.1 — Modular ROS 2 Foundation

This alpha starts physical decomposition of Nodrix without changing the current
Core package or stable 2.x contracts.

## Added

- independent `nodrix-ros2` Provider API 1 package;
- independent `nodrix-mapping` domain-contract package;
- one shared `rclpy.Context` and `MultiThreadedExecutor`;
- generic ROS 2 topic source and sink;
- typed `sensor_msgs/msg/PointCloud2` source;
- typed `nav_msgs/msg/Odometry` source;
- bounded latest-message inboxes;
- QoS configuration;
- metadata-first provider manifests and safe/deep probes;
- FAST-LIVO2 input pipeline;
- unit tests that do not require a running ROS graph.

## Not included yet

- TF2;
- message synchronization;
- Image and CameraInfo adapters;
- services and actions;
- rclcpp/native data plane;
- voxel map;
- occupancy/elevation maps;
- Nav2 integration;
- production signing keys.

## Package boundaries

```text
nodrix
├── current Core and compatibility layer
├── packages/nodrix-ros2
├── packages/nodrix-mapping
└── integrations/nodrix-fast-livo2
```

Core does not import either new package. Both packages depend only on the public
Nodrix 2.1 SDK and Provider API 1.
