# Nodrix 0.9.0 release notes

## Added

- explicit memory domains for host and device allocations;
- per-port memory contracts in Python and C++;
- static graph memory negotiation;
- `nodrix inspect --memory`;
- DLPack import/export for `ManagedBuffer` and `Tensor`;
- DMA-BUF plane/handle ownership model;
- CUDA IPC and external handle descriptors;
- native `_native_device` extension;
- `nodrix device doctor` and `nodrix device v4l2-probe`;
- executor-owned shared output slots;
- zero-copy outputs for allocator-aware isolated nodes;
- process-isolated synchronous sources;
- `execution.device`;
- `--template device`;
- C++ `device_memory.hpp`;
- C++ plugin ABI 3.

## Changed

- device-only buffers no longer pretend to expose a CPU `memoryview`;
- network/process serialization rejects opaque device buffers with an actionable error;
- process telemetry separates input copies, output copies and zero-copy outputs;
- project requirements target 0.9.0.

## Compatibility

Python node API remains compatible. C++ plugins must be rebuilt because plugin ABI changed from 2 to 3.

## Verified

- 49 Python/integration tests;
- C++ CTest 1/1;
- DLPack NumPy zero-copy round trip;
- DMA-BUF descriptor ownership using Linux `memfd`;
- process-isolated source;
- 32/32 executor-owned outputs with zero output copies;
- mixed Python → C++ → Python graph;
- native device extension and libav/V4L2 capability diagnostics.

## Not claimed as complete

Actual CUDA IPC mapping, DMA-BUF capture/requeue, hardware-specific importers, automatic device conversion nodes, native libav media nodes, and QUIC are not implemented in 0.9.0.
