# Media и vision

Plyctl объединяет media source, preprocessing, native inference, tracking, overlay, encoding, recording и stream publishing.

## Multi-rate pattern

```text
source frame clock ─┬─ latest frame → detector
                    └─ every frame  → realtime tracker
                                         │
                               overlay → hardware encoder
```

Detector path обычно использует `latest` capacity 1. Recording path должен быть lossless.

## Hardware-first encoding

Generated vision project использует `media.ffmpeg_encoder` с hardware probing и явным software fallback. В strict deployment требуйте acceleration, а не скрывайте CPU fallback.

## Команды

```bash
plyctl media doctor
plyctl media select-encoder h264
plyctl media probe INPUT
plyctl inspect --resolved
plyctl run
```
