# Nodrix 2.0.0

Nodrix 2.0.0 establishes the stable universal runtime line.

Highlights:

- strict Manifest v2 with explicit sections and a safe 1.x migrator;
- stable Python Node API and Plugin C ABI 2;
- lossless C ABI correlation metadata, explicit string ownership, and opaque
  device-memory handles;
- direct external C ABI source/processor/sink loading in the standalone native
  runner;
- portable native runner packaged in platform wheels, with runtime compilation
  disabled by default;
- native graceful signal shutdown, lifecycle events, live status, bounded
  queues, optional inputs, and multi-rate synchronization;
- reusable nested Fragments with public contracts;
- bounded lifecycle and fault policies including real fallback-node execution;
- automatic crash-safe recording with end-to-end correlation metadata;
- Ed25519-signed offline plugin packages and production verification;
- atomic immutable `.ndpkg` installation with traversal, symlink, filename,
  decompression, and size limits;
- production gate for security, health, hardware fallback, model paths, schemas,
  and memory copies;
- optional OpenTelemetry lifecycle tracing;
- optional ROS 2 source/sink adapters with QoS and timestamp mapping;
- Linux x86-64/ARM64, macOS and Windows CI coverage and capability matrix.

Release qualification also covers C11 ABI compilation, C++ SDK compilation,
external plugin error/mismatch/missing-symbol paths, zero-copy retention,
100,000-message normal E2E, a one-million-message stress path, ASan/UBSan,
queue TSan, NDRX2 mutation tests, bounded reconnect behavior, unpacked-sdist
tests, and wheel execution without runtime compilation.

Manifest v1 remains readable. New templates produce v2. Migrate without
overwriting the source:

```bash
nodrix migrate pipeline.yaml --to v2
nodrix validate pipeline.v2.yaml --strict
nodrix run pipeline.v2.yaml --production
```

The 2.x compatibility boundary covers public Python imports, Manifest v2 field
semantics, message correlation fields, lifecycle/health shape, Plugin C ABI 2,
wire schema checks, NDRX2 read compatibility, and `.ndpkg` verification.

The stable memory-domain contract does not imply that every accelerator has a
built-in operator. CPU in-process and shared-memory process paths are validated
in Core; opaque matching-domain device handles are preserved between native
C ABI nodes. Hardware-specific CUDA/DMA-BUF/Metal operators remain plugins and
must be qualified on their target hardware.
