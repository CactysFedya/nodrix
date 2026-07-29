# Reusable Blocks

Keep the graph in `pipeline.yaml` and replaceable node settings in `blocks/`.

```yaml
name: raspberry-vision
profile: realtime-low-latency
blocks:
  camera: blocks/camera.yaml
  detector: blocks/detectors/yolo26n-320.yaml
  tracker: blocks/trackers/bytetrack-fast.yaml
flow:
  - camera.frame -> detector.frame
  - detector.detections -> tracker.detections
```

A block contains one compact node configuration:

```yaml
use: vision.ncnn_detector
model: models/yolo26n-320.ncnn
imgsz: 320
conf: 0.18
```

Replace it temporarily:

```bash
nodrix run --block detector=blocks/detectors/rtdetr-640.yaml
```

Change one value:

```bash
nodrix run --set detector.conf=0.12
```

Inspect available files and the final graph:

```bash
nodrix block list
nodrix block inspect blocks/detectors/yolo26n-320.yaml
nodrix inspect --resolved
```

Blocks are configuration-only. They add no runtime boundary or overhead.
