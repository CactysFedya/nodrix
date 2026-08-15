# Compact Manifest

Nodrix 1.1 accepts both the canonical `nodrix.dev/v1` manifest and a shorter authoring form. Both resolve to the same `PipelineManifest`; runtime behavior, queues, memory planning, type checks and security are identical.

```yaml
name: raspberry-rtsp-preview
profile: realtime-low-latency

nodes:
  camera:
    uses: media.ffmpeg_source
    uri: ${RTSP_URL}

  encoder:
    uses: media.ffmpeg_encoder
    codec: h264
    encoder: auto

flow:
  - camera.frame -> encoder.frame

publish:
  /camera/front/h264:
    from: encoder.encoded
    access: token
```

Rules:

- `uses` is canonical. The old `use` spelling remains readable in Nodrix 2.x
  and is reported as deprecated by validation.
- Node keys other than lifecycle/execution fields become `parameters`.
- `flow` accepts `source.port -> target.port` strings or full edge mappings.
- `publish` becomes `streams.exports`.
- `access: token` uses `NODRIX_STREAM_TOKEN` unless `token_env` is explicitly supplied.
- Canonical and compact manifests can coexist in one repository.
- Optional `sessions`, `resources`, `applications`, bindings, and transported
  Edges keep their normal Provider API 2 shape; only local queue edges use the
  `flow` shorthand.

```yaml
sessions:
  ros:
    uses: ros2.session
    parameters: {distro: jazzy}
applications:
  driver:
    uses: ros2.launch
    bindings: {session: ros}
    package: demo_driver
    launch_file: driver.launch.py
  mapping:
    uses: ros2.launch
    bindings: {session: ros}
    package: demo_mapping
    launch_file: mapping.launch.py
nodes: {}
edges:
  - from: driver.points
    to: mapping.points
    transport:
      uses: ros2.topic
      parameters:
        topic: /points
        message_type: sensor_msgs/msg/PointCloud2
```

Inspect the exact canonical form:

```bash
nodrix inspect pipeline.yaml --resolved
nodrix config show pipeline.yaml
nodrix config show pipeline.yaml --output resolved.yaml
```

One-off override:

```bash
nodrix run --set nodes.encoder.crf=18 --set nodes.encoder.keyint=30
```

`nodes.encoder.crf` is normalized to `nodes.encoder.parameters.crf`.
