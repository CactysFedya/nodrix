# Nodrix roadmap after 1.2

## Completed in 1.1

Compact manifests, performance profiles, auto encoder selection, resolved
configuration and per-node resource telemetry.

## Completed in 1.2

Reusable single-node YAML Blocks, temporary `--block` replacement, short
block parameter overrides, block discovery/inspection and lock-file checksums.

## 1.3 — Vision Pack

Official inference adapters, preprocess/postprocess, tracking, Re-ID, overlays
and benchmark-ready examples. No algorithm is mandatory; each major stage
remains replaceable through a block.

## 1.4 — ROS 2 Bridge

Typed topics, message conversion, services/actions foundation, parameters,
rosbag/`.ndrx` conversion, and zero-copy-aware intra-host bridge paths.

## 1.5 — Hardware backends

Production CUDA IPC, V4L2 DMA-BUF capture/requeue, hardware frame import,
native libav nodes, and tested Raspberry Pi/NVIDIA paths behind the stable 1.x
memory API.

## 1.6 — Distributed orchestration

QUIC/UDP transports, stronger identity/TLS, multi-host launch and remote
lifecycle management. The data plane remains peer-to-peer.

## 2.0

Reserved for unavoidable breaking changes to the public Python SDK, manifest
format, wire format or Plugin ABI.
