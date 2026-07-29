# Multi-rate Vision graphs

## Goal

A real-time graph should not force every stage to run at the detector rate.
For example:

```text
camera       30 FPS
 detector    10 FPS, newest frame only
 tracker     30 FPS, prediction plus delayed updates
 overlay     30 FPS when downstream capacity permits
```

## Reference graph

```yaml
blocks:
  source: blocks/sources/ffmpeg.yaml
  preprocess: blocks/preprocess/letterbox-320.yaml
  detector: blocks/detectors/yolo26n-ncnn.yaml
  tracker: blocks/trackers/realtime-bytetrack.yaml
  overlay: blocks/outputs/overlay.yaml
  encoder: blocks/outputs/h264.yaml

flow:
  - from: source.frame
    to: preprocess.frame
    queue: {capacity: 1, policy: latest}

  - from: preprocess.frame
    to: detector.frame
    queue: {capacity: 1, policy: latest}

  - from: source.frame
    to: tracker.frame
    queue: {capacity: 2, policy: drop_oldest}

  - from: detector.detections
    to: tracker.detections
    queue: {capacity: 1, policy: latest}

  - from: source.frame
    to: overlay.frame
    queue: {capacity: 4, policy: drop_oldest}

  - from: tracker.tracks
    to: overlay.tracks
    queue: {capacity: 2, policy: drop_oldest}
```

## Tracker block

```yaml
use: vision.realtime_bytetrack

synchronization:
  policy: latest_available
  trigger_port: frame

backend: native
track_thresh: 0.25
low_thresh: 0.10
match_iou: 0.30
second_match_iou: 0.20
track_buffer: 60
min_hits: 1

max_prediction_frames: 15
prediction_score_decay: 0.97
delayed_measurement_replay: true
history_frames: 60
too_old_policy: discard
```

The `frame` port is the required trigger and `detections` is an optional
side input. Tracking therefore starts on the first source frame, builds bounded
history before the detector finishes, and consumes the newest available
detection when one exists. The tracker remembers the last applied detection
sequence and never applies one measurement twice.

## Delayed measurement replay

When a detection for sequence 100 arrives while the source is already at 103:

1. restore tracker state immediately before frame 100;
2. predict to frame 100 and apply the measurement;
3. predict again through 101, 102 and 103;
4. publish current tracks with sequence 103.

State history is bounded by `history_frames`. Measurements older than retained
history are discarded by default. `too_old_policy: current` is available as an
explicit approximate mode.

## Queue meanings

- `latest` intentionally replaces stale work. It is not an error.
- `drop_oldest` preserves a small recent history while bounding memory.
- `drop_newest` indicates downstream congestion and is reported as overflow.
- synchronization misses are counted separately from queue replacement.

Use `nodrix top` to compare source, detector, tracker and output rates and to
identify the actual end-to-end bottleneck.
