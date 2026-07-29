# Nodrix device-memory model

## Goal

A graph must preserve the original allocation whenever adjacent nodes can consume the same memory domain. Nodrix must not hide CPU copies, device transfers, format conversions, or synchronisation.

## ManagedBuffer

`ManagedBuffer` now represents both host-accessible storage and opaque device allocations.

```python
buffer.memory_type
buffer.device
buffer.nbytes
buffer.host_accessible
buffer.handle
buffer.metadata
```

Host-backed buffers support `memoryview()`. Device-only buffers intentionally reject it.

## Domains

| Domain | Typical producers/consumers |
|---|---|
| `cpu` | NumPy, OpenCV, ordinary C++ buffers |
| `pinned_cpu` | asynchronous GPU transfer staging |
| `shared` | isolated Nodrix processes |
| `dma_buf` | V4L2, DRM, VAAPI, hardware codecs |
| `cuda` | PyTorch CUDA, TensorRT, CUDA kernels |
| `rocm` | ROCm tensors |
| `vulkan` | Vulkan compute/image backends |
| `opencl` | OpenCL buffers |
| `metal` | Apple Metal |
| `npu` | vendor accelerators and oneAPI devices |
| `external` | backend-defined opaque allocation |

## No hidden host fallback

```python
tensor.numpy(copy=False)
```

works only for host-accessible memory. A device tensor requires an explicit transfer or a consumer using DLPack/device handles.

## Isolated outputs

`NodeContext.allocate_buffer()` and `Node.allocate_output()` allocate a block owned by the parent executor. The isolated child writes into that block and returns a shared-memory descriptor.

This fixes the 0.8.0 output path:

```text
0.8: child CPU output → one-shot shared segment → parent
0.9: parent output slot → child writes directly → descriptor → parent
```

## Plugin C ABI

Plugin C ABI 2.0 includes a memory string in `nodrix_port_v2` and a device
field in `nodrix_node_context_v2`.
