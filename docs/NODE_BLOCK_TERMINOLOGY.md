# Node types, instances and blocks

Nodrix uses four related terms:

- **Node type** — executable implementation, for example
  `vision.ncnn_detector`.
- **Node instance** — a named occurrence in one pipeline, for example
  `detector`.
- **Block** — a reusable YAML preset for one node instance. It contains
  `use:` and all normal parameters for that implementation.
- **Fragment** — a future reusable subgraph containing multiple nodes.

A normal project keeps block-local parameters together:

```yaml
# blocks/detectors/yolo26n-ncnn.yaml
use: vision.ncnn_detector
model: models/yolo26n_ncnn_model
conf: 0.18
iou: 0.65
max_det: 150
threads: 3
output_format: auto
has_objectness: auto
```

The pipeline only chooses blocks and connects their ports.
