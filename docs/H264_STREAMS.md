# H.264/H.265 Nodrix streams

## Encoder

```yaml
encoder:
  uses: media.ffmpeg_encoder
  parameters:
    codec: h264
    encoder: libx264
    preset: ultrafast
    tune: zerolatency
    fps: 30
    keyint: 30
```

The encoder process persists for the node lifetime. Raw BGR8 frames are written from `ManagedBuffer` to FFmpeg stdin. Encoded Annex-B bytes are read from stdout and emitted as ordered `vision.encoded_frame` chunks.

Chunks are not forced into one-message-per-frame boundaries. Avoiding that parser saves another allocation and copy. The stateful decoder accepts arbitrary ordered chunks.

## Export

```yaml
streams:
  exports:
    - name: /camera/front/h264
      from: encoder.encoded
      queue:
        capacity: 2
        policy: latest
```

## View

```bash
nodrix-viewer /camera/front/h264
```

The viewer creates one persistent FFmpeg decoder with low probe/analyze settings. A dedicated receive thread continues draining the network while the UI stores only the newest decoded frame.

## Record without re-encoding

```yaml
writer:
  uses: media.encoded_writer
  parameters:
    path: output.h264
    codec: h264
```

or record the stream in `.ndrx` together with detections and tracks.

## Hardware encoders

The explicit encoder parameter can select an FFmpeg hardware backend, for example:

```yaml
encoder: h264_v4l2m2m
```

Availability in `ffmpeg -encoders` does not guarantee that the current device, driver, pixel format, and permissions support it. Check with `nodrix media doctor` and a short pipeline run.
