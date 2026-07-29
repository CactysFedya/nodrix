# DMA-BUF and native I/O

## Descriptor

`DmaBufHandle` contains one or more planes:

```text
fd
offset
length
stride
bytes_used
```

The handle also stores dimensions, pixel format, DRM modifier, device and metadata.

## Ownership

`dmabuf_from_fds(..., duplicate=True)` duplicates each file descriptor, so the Nodrix handle has independent ownership. `close()` releases duplicated descriptors.

## Frame wrapper

`Frame.from_dmabuf()` creates a device-only frame. It does not mmap or copy the buffer automatically.

## Native V4L2 probe

The `_native_device` C++ extension calls `VIDIOC_QUERYCAP` directly:

```bash
nodrix device v4l2-probe /dev/video0
```

It reports driver, card, bus, streaming support and capture capabilities without starting a stream.

## Current boundary

0.9.0 defines the safe ownership contract and native capability probe. A complete capture backend must additionally implement request buffers, queue/dequeue, optional `VIDIOC_EXPBUF`, lifecycle leases and delayed buffer requeue. That backend is not claimed as complete in this release.
