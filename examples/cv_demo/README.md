# CV pipeline example

This example demonstrates the extension model rather than a built-in YOLO dependency.
Every algorithmic stage is a user node loaded from `nodes.py`:

```text
Synthetic camera
→ Frame adapter
→ Custom detector
→ Custom tracker
→ Track filter
→ Custom Re-ID
├→ Console output
└→ JSONL recording
```

Run:

```bash
nodrix validate pipeline.yaml
nodrix inspect pipeline.yaml
nodrix run pipeline.yaml
nodrix benchmark pipeline.yaml --warmup 1 --repeat 5
```

A real project can replace each class independently while preserving typed ports:

```text
vision.frame → vision.detections → vision.tracks → vision.identified_tracks
```
