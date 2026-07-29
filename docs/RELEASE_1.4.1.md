# Nodrix 1.4.1 — Runtime UX and Vision Hardening

Nodrix 1.4.1 is a patch release based on a real Raspberry Pi 5
detector-to-viewer deployment.

## Block-local configuration

Generated Vision projects no longer require environment exports or a
shared project configuration file. Every replaceable node preset contains
its implementation, parameters and comments in one YAML file:

```text
blocks/sources/ffmpeg.yaml
blocks/preprocess/letterbox-320.yaml
blocks/detectors/yolo26n-ncnn.yaml
blocks/trackers/bytetrack.yaml
blocks/outputs/overlay.yaml
blocks/outputs/h264.yaml
```

`pipeline.yaml` contains only the selected blocks, graph connections,
queue policies and exported streams. Environment placeholders remain
supported by the manifest language for Docker, CI and deployment secrets,
but the default Vision template does not use them.

## Runtime UX

- compact graph-oriented `nodrix inspect`;
- `nodrix inspect --node detector`;
- parameter documentation in `nodrix node info`;
- startup summary before execution;
- selected H.264/H.265 encoder explanation;
- `nodrix top` uses one Rich Live display;
- process CPU/RSS are shown once;
- in-process node timing is labelled `Busy`.

## Vision fixes

- generated test source and declared input are both 15 FPS;
- NCNN starts with three threads on Raspberry Pi 5;
- source-to-overlay keeps a bounded four-frame history using
  `drop_oldest`;
- H.264 encoder FPS is inferred from incoming frame metadata;
- generated YAML contains parameter comments;
- the ordinary Vision template does not create an unused native example.

## Viewer fixes

- normal publisher shutdown is end-of-stream, not a failure;
- exact H.264/H.265 latency is hidden while the transport remains
  arbitrary encoded chunks rather than timestamped access units.
