# H.264 and H.265 Streams

Encode once with a persistent FFmpeg node:

```yaml
encoder:
  uses: media.ffmpeg_encoder
  parameters:
    codec: h264
    encoder: libx264
    preset: ultrafast
    tune: zerolatency
    fps: 30
```

The `vision.encoded_frame` output can simultaneously feed:

- `media.encoded_writer`;
- `record.ndrx_writer`;
- a named Nodrix stream;
- `nodrix-viewer` on another computer.

```bash
nodrix-viewer /camera/front/h264
```

The viewer uses one persistent decoder and keeps only the most recent decoded
frame, so old frames do not accumulate in the display queue.
