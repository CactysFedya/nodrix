# Nodrix 1.2.0 — Reusable Blocks

Nodrix 1.2.0 introduces the smallest useful form of composable configuration:
reusable single-node YAML blocks.

## Added

- top-level `blocks:` mapping in compact manifests;
- one-file, one-node block format using the existing compact node syntax;
- repeatable `--block name=path.yaml` for `run`, `validate`, `inspect`,
  `benchmark`, and configuration commands;
- short overrides such as `--set detector.conf=0.12`;
- `nodrix block list` and `nodrix block inspect`;
- exact block-file checksums in `nodrix.lock`;
- a block-based `vision` project template;
- resolved configuration source tracking for block values.

## Compatibility

Blocks are expanded before Pydantic validation and graph construction. The
runtime receives the same canonical `PipelineManifest` used in Nodrix 1.1.
No process, queue, copy, serialization step, or ABI boundary is added.

Nodrix 1.2.0 preserves:

- the public Python Node API;
- Plugin ABI 1.0;
- the wire protocol;
- `.ndrx` recordings;
- `.ndpkg` packages;
- canonical pipeline manifests;
- existing compact manifests without `blocks:`.
