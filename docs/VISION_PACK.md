# Vision Pack

Nodrix 1.3.0 adds the first ready-to-compose perception vertical slice. It is
built on the existing `vision.frame`, `vision.detections` and `vision.tracks`
contracts and does not require a user-written detector or tracker node.

## Built-in nodes

### `vision.letterbox`

Resizes a BGR8 frame while preserving aspect ratio, pads it to the requested
shape and stores the reversible transform in `Frame.metadata["letterbox"]`.

Parameters:

- `imgsz`: integer or `[height, width]`;
- `scale_up`: permit enlargement, default `true`;
- `color`: scalar or BGR triplet, default `[114, 114, 114]`;
- `interpolation`: optional OpenCV interpolation constant.

### `vision.ncnn_detector`

Loads one NCNN `.param`/`.bin` pair and emits `Detections` in source-frame pixel
coordinates. `model` can name a directory, `.param`, `.bin`, or a common file
prefix. Explicit `param` and `bin` are also supported.

The decoder supports:

- `N x 6` output: `x1, y1, x2, y2, score, class_id`;
- `N x (4 + classes)` modern Ultralytics output;
- `N x (5 + classes)` objectness-based output;
- candidate-major and feature-major tensors with singleton batch dimensions.

Important parameters:

- `model`, or `param` + `bin`;
- `labels` or `labels_file`;
- `conf`, `iou`, `max_det`;
- `threads`, `use_vulkan`;
- `input_blob`, `output_blob` when model names cannot be discovered;
- `has_objectness`, `num_classes`, `classes`, `class_agnostic`.

The initial backend uses the NCNN Python binding. It is a production functional
baseline, not yet the future C ABI/native inference implementation.

### `vision.bytetrack`

A dependency-light ByteTrack-style tracker:

1. predicts active tracks with a constant-velocity Kalman filter;
2. associates high-confidence detections by IoU;
3. uses low-confidence detections to recover unmatched tracks;
4. creates new tracks only from sufficiently confident unmatched detections;
5. keeps bounded state using `track_buffer`.

It intentionally avoids SciPy/LAP to remain straightforward to install on edge
devices. The assignment is deterministic greedy IoU rather than the full
reference ByteTrack linear-assignment implementation.

### `vision.overlay`

Synchronizes `frame` and `tracks`, draws boxes, track IDs, classes and scores,
and emits a new immutable BGR8 frame.

## Memory behavior

The 1.3.0 reference path is explicit host memory:

```text
FFmpeg pipe BGR8 -> OpenCV letterbox -> NCNN Python binding
                 -> metadata detections/tracks
original BGR8 -> OpenCV overlay -> FFmpeg encoder pipe
```

Large buffers are not serialized between in-process nodes, but letterbox and
overlay necessarily create new image buffers. The NCNN binding may perform its
own layout/import conversion. Nodrix does not describe this path as end-to-end
zero-copy.

## Failure and overload behavior

- every edge remains bounded by the normal Nodrix queue contract;
- `latest` is recommended for live preview edges;
- missing model files fail during node startup;
- missing optional NCNN/OpenCV dependencies fail with actionable messages;
- malformed model output fails instead of silently producing wrong boxes;
- tracker state is bounded by `track_buffer` and the incoming object count.

## Reference pipeline

See `examples/vision_production/pipeline.yaml`.
