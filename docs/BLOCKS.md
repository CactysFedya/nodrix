# Reusable Blocks

Nodrix 1.2 adds a deliberately small configuration feature for replacing one
node without rewriting the whole pipeline. A block is a YAML file containing
one normal Nodrix node configuration.

## Project layout

```text
vision_project/
├── pipeline.yaml
├── blocks/
│   ├── camera.yaml
│   ├── detectors/
│   │   ├── yolo26n-320.yaml
│   │   └── rtdetr-640.yaml
│   ├── trackers/
│   │   └── bytetrack-fast.yaml
│   └── outputs/
│       └── lan-preview.yaml
├── nodes/
└── models/
```

Use one file for one replaceable function: camera, detector, tracker, Re-ID,
recorder, or output. Do not split every resize, normalization, or NMS operation
into a separate file unless it is independently replaceable.

## Main pipeline

```yaml
name: raspberry-vision
profile: realtime-low-latency

blocks:
  camera: blocks/camera.yaml
  detector: blocks/detectors/yolo26n-320.yaml
  tracker: blocks/trackers/bytetrack-fast.yaml
  output: blocks/outputs/lan-preview.yaml

flow:
  - camera.frame -> detector.frame
  - detector.detections -> tracker.detections
  - camera.frame -> output.frame
  - tracker.tracks -> output.tracks
```

The block name becomes the node name. Existing `flow` and `publish` references
therefore remain readable and stable.

## Block file

```yaml
use: vision.ncnn_detector
model: models/yolo26n-320.ncnn
imgsz: 320
conf: 0.18
iou: 0.65
max_det: 150
threads: 4
```

The format is exactly the compact node format already supported inside
`nodes:`. Reserved fields such as `execution`, `health`, `failure`, `memory`,
`inputs`, and `outputs` keep their normal meaning. Other fields become node
parameters.

Paths inside a block are project-root relative. This keeps blocks easy to move
between category directories without silently changing model or node paths.

## Replace a block

Change one line in `pipeline.yaml`:

```yaml
blocks:
  detector: blocks/detectors/rtdetr-640.yaml
```

For a temporary experiment, do not edit the file:

```bash
nodrix run pipeline.yaml \
  --block detector=blocks/detectors/rtdetr-640.yaml
```

Validate the replacement first:

```bash
nodrix validate pipeline.yaml --strict \
  --block detector=blocks/detectors/rtdetr-640.yaml
```

## Change one parameter

Block names can be used as short parameter paths:

```bash
nodrix run pipeline.yaml \
  --set detector.conf=0.12 \
  --set detector.imgsz=416
```

The equivalent canonical paths are:

```text
nodes.detector.parameters.conf
nodes.detector.parameters.imgsz
```

## Find and inspect blocks

```bash
nodrix block list
nodrix block inspect blocks/detectors/yolo26n-320.yaml
```

Machine-readable output:

```bash
nodrix block list --json
nodrix block inspect blocks/detectors/yolo26n-320.yaml --json
```

## See the actual graph

```bash
nodrix inspect pipeline.yaml --resolved
```

The resolved output contains ordinary canonical `nodes` and `edges`; `blocks`
no longer exist at runtime.

```text
pipeline.yaml + selected block YAML files
                    ↓ configuration resolution
             one canonical Nodrix graph
                    ↓ normal optimization/build
                 runtime execution
```

A block boundary does not create a process, queue, copy, serializer, or network
connection. Runtime behavior is determined only by the resolved node and edge
configuration.

## Reproducibility

`nodrix lock` records the checksum of every block actually referenced by the
pipeline. Unused alternative blocks are not locked.

```bash
nodrix lock
nodrix lock --check
```

Runtime overrides are intentionally incompatible with `--locked`:

```text
--locked + --block  rejected
--locked + --set    rejected
--locked + --profile rejected
```

To lock a new detector permanently, change its path in `pipeline.yaml` and
regenerate `nodrix.lock`.

## Naming rules

Prefer descriptive names:

```text
yolo26n-320-ncnn.yaml
rtdetr-640-onnx.yaml
bytetrack-fast.yaml
rtsp-low-latency.yaml
h264-lan-preview.yaml
```

Avoid names such as `new.yaml`, `test2.yaml`, or `final-final.yaml`.
