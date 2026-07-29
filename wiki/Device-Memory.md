# Device Memory

Introduced in 0.9 and stabilized in Nodrix 1.0, the runtime models CPU, shared, DMA-BUF, CUDA/ROCm, Vulkan/OpenCL/Metal, NPU and external allocations explicitly.

```bash
nodrix device doctor
nodrix inspect --memory
```

Device-only buffers never expose an implicit CPU `memoryview`. Use DLPack or the corresponding device backend.

See the repository documentation for DLPack, DMA-BUF ownership and isolated output allocation.
