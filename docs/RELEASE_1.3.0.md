# Nodrix 1.3.0 — Production Vision Vertical Slice

Nodrix 1.3.0 turns the existing media and typed-data foundations into the first
complete perception pipeline that can be described entirely with built-in
nodes.

## Added

- `vision.letterbox` with reversible source-coordinate metadata;
- `vision.ncnn_detector` with model/label resolution and common YOLO output decoding;
- deterministic NumPy NMS and class filtering;
- `vision.bytetrack` with two-stage association and constant-velocity Kalman state;
- `vision.overlay` for tracked-object preview;
- `vision-ncnn` optional dependency group;
- reusable production vision blocks and a complete H.264 streaming example;
- unit and fake-backend tests that do not require NCNN in the normal CI matrix;
- Vision Pack architecture, memory and overload documentation.

## Compatibility

The release preserves the Nodrix 1.x manifest, node, block and message APIs.
Existing pipelines remain source-compatible. NCNN is optional and is not added
to the broad `all` dependency set so generic CI and non-vision installations do
not depend on platform wheel availability.

## Known boundaries

- the reference path uses host BGR8 memory;
- inference uses the NCNN Python binding, not the future stable native C ABI;
- the tracker implements ByteTrack-style two-stage IoU association, not an exact
  copy of the original project and its LAP solver;
- model export remains external to Nodrix;
- NCNN model input/output conventions vary, so blob names and decoding options
  remain configurable.

## Release gate

- full Python test matrix 3.11–3.14;
- native C++ and sanitizer jobs inherited from 1.2.1;
- Vision Pack unit tests;
- source and wheel build plus `twine check`;
- real Raspberry Pi 5 smoke test with an exported NCNN model before tagging.
