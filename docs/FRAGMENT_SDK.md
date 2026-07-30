# Fragment SDK

A Fragment is a reusable, versioned subgraph with public ports:

```yaml
version: 1.0.0
description: Detection and tracking
documentation: README.md
tests: [tests/test_contract.py]
parameters:
  detector.conf: 0.25
inputs:
  frame: detector.frame
outputs:
  tracks: tracker.tracks
nodes:
  detector:
    uses: vision.ncnn_detector_native
  tracker:
    uses: vision.realtime_bytetrack
edges:
  - from: detector.detections
    to: tracker.detections
fragments: {}
hardware_requirements: [ncnn]
```

`blocks:` may replace an internal node with a self-contained Block YAML. A
Fragment instance may override that mapping explicitly; paths resolve relative
to the Fragment package.

Create and validate a package:

```bash
nodrix fragment init my-fragment
nodrix fragment validate my-fragment/fragment.yaml
```

Reference it from Manifest v2:

```yaml
fragments:
  perception:
    uses: fragments/perception/fragment.yaml
    parameters:
      detector.conf: 0.18
edges:
  - from: source.frame
    to: perception.frame
  - from: perception.tracks
    to: sink.input
```

Expansion is deterministic. Internal node names are namespaced, public edges
are rewritten before graph validation, and nested Fragments are supported.
