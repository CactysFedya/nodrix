# Gradual Python-to-C++ migration

Nodrix is designed so Python is the initial implementation language, not a temporary architecture that must later be discarded.

## Stable graph interface

Keep these stable from the first Python version:

```text
node name
input port names and types
output port names and types
parameters
message schemas
timestamp/sequence behavior
```

Example:

```yaml
tracker:
  uses: ./tracker.py:Tracker
  inputs:
    frame: vision.frame
    detections: vision.detections
  outputs:
    tracks: vision.tracks
```

## Stage 1 — synchronous Python

```python
class Tracker(Node):
    def open(self, context):
        self.tracker = PythonTracker(self.parameters)

    def process(self, inputs):
        return {"tracks": self.tracker.update(inputs)}
```

This already runs on the hybrid C++ queue data plane.

## Stage 2 — use native libraries from Python

Keep the same node class while moving heavy work into OpenCV, NumPy, ONNX Runtime, PyTorch, NCNN bindings, or another native library. The graph does not change.

## Stage 3 — compiled backend behind the same wrapper

```python
try:
    from _tracker_native import update
except ImportError:
    from tracker_python import update
```

The wrapper, ports, parameters, and manifest remain unchanged. A compiled extension can consume NumPy/OpenCV memory through the buffer protocol without copying and can release the GIL.

See `examples/python_to_cpp` for a complete tested example.

## Stage 4 — full native plugin

When startup, state, scheduling, and output allocation must all be native, replace only `uses`:

```yaml
uses: native:./libtracker.so#tracker
```

Retain the same `inputs`, `outputs`, parameters, and edges. The rest of the pipeline is not rewritten.

## What may still change

A C++ implementation may require explicit binary schemas for complex payloads rather than arbitrary Python dictionaries. Define standard `vision.detections`, `vision.tracks`, `vision.embedding`, and custom message schemas early to avoid this migration cost.
