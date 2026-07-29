# Media Pack

Nodrix 0.7.0 uses persistent FFmpeg processes for low-latency decode and H.264/H.265 recording.

## Nodes

- `media.ffmpeg_source`
- `media.ffmpeg_writer`
- `media.encoded_writer`

## Commands

```bash
nodrix media doctor
nodrix media probe input.mp4
nodrix media record rtsp://camera/live record.mkv --copy
nodrix media relay input.mp4 srt://host:9000 --copy
```

## Viewer

```bash
nodrix-viewer rtsp://camera/live --decoder ffmpeg --rtsp-transport tcp
```

Use a separate preview branch with `latest:1` so that display never blocks inference or recording.
