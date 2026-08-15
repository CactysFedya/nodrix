# Media and vision integration

Plyctl can combine media sources, preprocessors, native inference, tracking, overlays, encoders, recording, and stream publication.

## Multi-rate real-time pattern

```text
source frame clock ─┬─ latest frame → detector (slower)
                    └─ every frame  → real-time tracker
                                         │
                               overlay → hardware encoder
```

The detector path normally uses `latest` with capacity 1. The source-to-tracker clock and bounded history preserve smooth track prediction between detections. Recording paths should use lossless queue semantics.

## Hardware-first encoding

Generated vision projects use `media.ffmpeg_encoder` with automatic hardware probing and an explicit software fallback. For a strict deployment, require acceleration rather than silently accepting CPU encoding.

## Operations

```bash
plyctl media doctor
plyctl media select-encoder h264
plyctl media probe INPUT
plyctl inspect --resolved
plyctl run
```

## Remote viewing

Published streams can be discovered on the LAN and opened by the viewer. Keep binding, authentication, and exposure explicit in production.
