# Compact Manifest

Nodrix 1.1 accepts both the canonical `nodrix.dev/v1` manifest and a shorter authoring form. Both resolve to the same `PipelineManifest`; runtime behavior, queues, memory planning, type checks and security are identical.

```yaml
name: raspberry-rtsp-preview
profile: realtime-low-latency

nodes:
  camera:
    use: media.ffmpeg_source
    uri: ${RTSP_URL}

  encoder:
    use: media.ffmpeg_encoder
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

- `use` is the compact alias of `uses`.
- Node keys other than lifecycle/execution fields become `parameters`.
- `flow` accepts `source.port -> target.port` strings or full edge mappings.
- `publish` becomes `streams.exports`.
- `access: token` uses `NODRIX_STREAM_TOKEN` unless `token_env` is explicitly supplied.
- Canonical and compact manifests can coexist in one repository.

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
