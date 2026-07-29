# Nodrix 2.0.0

Nodrix 2.0.0 establishes the stable universal runtime line.

Highlights:

- strict Manifest v2 with explicit sections and a safe 1.x migrator;
- stable Python Node API and Plugin C ABI 2;
- reusable nested Fragments with public contracts;
- bounded lifecycle and fault policies including real fallback-node execution;
- automatic crash-safe recording with end-to-end correlation metadata;
- Ed25519-signed offline plugin packages and production verification;
- production gate for security, health, hardware fallback, model paths, schemas,
  and memory copies;
- optional OpenTelemetry lifecycle tracing;
- optional ROS 2 source/sink adapters with QoS and timestamp mapping;
- Linux x86-64/ARM64, macOS and Windows CI coverage and capability matrix.

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
