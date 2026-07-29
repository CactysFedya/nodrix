# Nodrix 1.1.0 — Compact Configuration and Resource Telemetry

Nodrix 1.1 keeps Plugin ABI 1.0, the wire protocol, `.ndrx`, `.ndpkg`, lock-file and public Node API compatible with 1.0.

New capabilities:

- compact pipeline manifests;
- five built-in runtime profiles;
- `--profile` and repeatable `--set path=value` overrides;
- `nodrix inspect --resolved`;
- `nodrix config show`, `profiles` and `explain`;
- `encoder: auto` with real FFmpeg probe and software fallback;
- `nodrix media select-encoder`;
- per-node CPU/memory/queue telemetry and `nodrix top`;
- CPU/RAM columns in `status` and `inspect --live`;
- publisher bitrate, drops, subscribers, node CPU and device temperature overlay in `nodrix-viewer` when the metrics endpoint is available;
- compact `vision` and `media` project templates.

No additional serialization, copy or queue is introduced by compact manifests or profiles. They are resolved before graph construction.
