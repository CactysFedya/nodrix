# Nodrix roadmap after 1.0

## 1.1 — ROS 2 Bridge

Typed topics, message conversion, services/actions foundation, parameters, rosbag/`.ndrx` conversion, and zero-copy-aware intra-host bridge paths.

## 1.2 — Vision Pack

Official inference adapters, preprocess/postprocess, tracking, Re-ID, overlays and benchmark-ready examples. No algorithm is mandatory; all remain replaceable nodes.

## 1.3 — Hardware backends

Production CUDA IPC, V4L2 DMA-BUF capture/requeue, hardware frame import, native libav nodes, and tested Raspberry Pi/NVIDIA paths behind the stable 1.x memory API.

## 1.4 — Distributed orchestration

QUIC/UDP transports, stronger identity/TLS, multi-host launch and remote lifecycle management. The data plane remains peer-to-peer.

## 2.0

Reserved for unavoidable breaking changes to the public Python SDK, manifest format, wire format or Plugin ABI.
