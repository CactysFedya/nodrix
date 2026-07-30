# Native NCNN qualification

`vision.ncnn_detector_native` is an official Plugin C ABI 2 provider. Every
published platform wheel must satisfy the build and smoke gates below.

## Artifact gates

- NCNN source version and SHA-256 match the values in native CMake;
- the platform library is present under `nodrix/bin`;
- no external NCNN shared-library dependency remains;
- the wheel imports with `NODRIX_ALLOW_RUNTIME_BUILD=0`;
- `nodrix doctor --provider vision` reports `native_ncnn: true`.

## Correctness gates

- C++ golden tests cover modern Ultralytics, objectness, transposed, xyxy,
  class filtering, deterministic NMS, invalid configuration, and Unicode;
- the real NCNN library compiles, links, loads, and executes one model;
- real target models are compared against the Python or standalone reference
  using identical frames, thresholds, blobs, and input geometry;
- counts, class ids, scores, and box IoU stay inside documented tolerances;
- empty and maximum-detection frames remain valid.

## Target-device gates

For Raspberry Pi, Jetson, or another edge target, record at least:

- detector FPS and P50/P95 latency;
- full-pipeline input/output FPS;
- CPU, RAM, temperature, and throttling;
- stale frames, queue drops, and planned/observed copies;
- one-hour memory stability and clean Ctrl+C shutdown.

Target performance is a hardware/model qualification, not a portable claim
made by the generic package.
