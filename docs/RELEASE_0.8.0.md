# Nodrix 0.8.0 — Data Plane

## Added

- `SharedBufferPool` and `SharedBufferDescriptor` public SDK.
- Descriptor-based transfer for shared payloads.
- Automatic shared-memory staging for large ordinary CPU payloads.
- `execution.isolation: process` for processor and sink nodes.
- CPU affinity and restart/skip/stop failure policies.
- Per-node copy, restart, and pool telemetry.
- `nodrix inspect --live`.
- Universal indexed `.ndrx` writer/reader.
- `nodrix record`, `nodrix play`, and `nodrix recording info`.
- `record.ndrx_source` and `record.ndrx_writer` nodes.
- Persistent `media.ffmpeg_encoder` producing H.264/H.265 Nodrix chunks.
- Persistent H.264/H.265 decoding in `nodrix-viewer`.
- `data-plane` project template.
- `nodrix data-plane doctor`.

## Changed

- Media template now encodes once and fans the same H.264 chunks to a writer and network stream.
- `Message` and `ManagedBuffer` can retain transport leases without exposing them in the wire format.
- Wire decoding can construct typed messages directly over shared-memory/file-backed views.

## Compatibility

The public CLI remains `nodrix`; no legacy `vpipe` or `visionpipe` aliases are restored. Existing 0.7 manifests continue to validate. New process/memory settings are optional.

## Known limits

- Process-isolated sources are deferred.
- Child output ownership transfer is not yet zero-copy.
- Shared-memory implementation is currently verified on Linux x86-64.
- QUIC/UDP, CUDA IPC, DMA-BUF, and ROS 2 bridge remain future work.
