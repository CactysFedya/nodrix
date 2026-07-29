# Nodrix 0.7.0 — Media Pack

Nodrix 0.7.0 adds a production-oriented FFmpeg media layer while preserving Nodrix Core as a universal typed graph runtime.

## Included

- Empty-by-default project initialization.
- Explicit runnable project templates.
- New `media` template.
- Persistent FFmpeg decoder node.
- Persistent H.264/H.265 writer node.
- Explicit hardware encoder selection.
- Encoded access-unit writer without re-encoding.
- Media probe, doctor, recording and relay commands.
- FFmpeg mode in Nodrix Viewer.
- RTSP transport selection.

## Not included

- Embedded RTSP server.
- GStreamer nodes.
- Universal `.ndrx` record/play for arbitrary typed messages.
- Hardware-specific zero-copy surfaces such as DMA-BUF/CUDA IPC.

These are candidates for 0.8.0 rather than hidden behind incomplete implementations.
