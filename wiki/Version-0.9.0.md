# Nodrix 0.9.0 Device Memory Contract

Highlights:

- DLPack tensor interoperability;
- DMA-BUF and CUDA IPC descriptors;
- per-port memory contracts;
- `nodrix inspect --memory`;
- zero-copy executor-owned output buffers for isolated nodes;
- process-isolated synchronous sources;
- native V4L2/libav capability diagnostics;
- C++ plugin ABI 3;
- `device` project template.

The release intentionally does not claim complete CUDA IPC mapping or V4L2 DMA-BUF capture. Those require target hardware backends.
