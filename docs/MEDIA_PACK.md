# Nodrix Media Pack 0.7.0

## Design goals

1. Keep the inference branch independent from preview/recording.
2. Keep one decoder or encoder process alive for the entire node lifetime.
3. Avoid JSON and per-frame subprocess creation in the media data path.
4. Permit software and hardware FFmpeg encoders through the same manifest.
5. Allow direct packet recording/relay when decoding is unnecessary.

## FFmpeg source

```yaml
nodes:
  input:
    uses: media.ffmpeg_source
    parameters:
      uri: rtsp://192.168.1.20/live
      rtsp_transport: tcp
      low_latency: true
```

For files, FFprobe resolves width, height and FPS. For `lavfi` sources these values are supplied explicitly:

```yaml
parameters:
  uri: lavfi:testsrc=size=640x360:rate=30
  width: 640
  height: 360
  fps: 30
```

The node runs one FFmpeg decoder and reads BGR24 frames into per-message byte buffers. Downstream Nodrix fan-out remains reference based.

## H.264/H.265 writer

```yaml
nodes:
  recorder:
    uses: media.ffmpeg_writer
    parameters:
      path: video/result.mp4
      codec: h264
      encoder: libx264
      preset: ultrafast
      tune: zerolatency
      crf: 23
      fps: 30
      keyint: 30
```

Hardware encoder examples:

```yaml
encoder: h264_v4l2m2m      # Raspberry Pi/Linux V4L2
encoder: h264_nvenc         # NVIDIA
encoder: h264_videotoolbox  # macOS
encoder: h264_vaapi         # Intel/AMD VAAPI; device setup may be required
```

Availability in `ffmpeg -encoders` does not guarantee that the current machine has the required hardware/device permissions. Check with:

```bash
nodrix media doctor
```

## Encoded writer

```yaml
nodes:
  raw_h264:
    uses: media.encoded_writer
    parameters:
      path: video/stream.h264
      codec: h264
```

This writes existing `vision.encoded_frame` buffers directly. It does not decode, transform or re-encode them.

## Record and relay

```bash
nodrix media record rtsp://camera/live camera.mkv --copy
nodrix media record input.mp4 output.mp4 --transcode --codec h265
nodrix media relay input.mp4 srt://192.168.1.55:9000 --copy
```

`--copy` is the fastest route because compressed packets stay compressed. Transcoding should only be used when codec, bitrate, resolution or compatibility must change.

## Viewer

```bash
nodrix-viewer rtsp://camera/live --decoder ffmpeg --rtsp-transport tcp
```

For RTSP/SRT/UDP, `auto` selects the FFmpeg reader. Local files and cameras continue to use OpenCV by default unless `--decoder ffmpeg` is specified.

## Latency recommendations

- Keep detector and recorder on separate edges.
- Use `capacity: 1, policy: latest` for preview.
- Use `block` for lossless offline recording.
- Prefer encoded packet relay/record over decode/re-encode.
- Use H.264 with no B-frames and `zerolatency` for interactive preview.
- Use TCP when packet loss is unacceptable; use UDP/SRT when lower latency is more important and the network supports it.
