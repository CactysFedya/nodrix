# Nodrix 1.7.0

Nodrix 1.7 makes recordings and run provenance suitable for long-running
production pipelines.

## NDRX2

New recordings use independently checksummed checkpoint chunks. The writer
retains only the active chunk index, so memory usage is bounded by
`checkpoint_records` rather than recording duration. The default is 1024
records and each checkpoint is flushed and synchronized before the next chunk.

On interruption, a reader verifies every completed chunk and scans the active
chunk for complete wire records. A partial final record is ignored. A checksum
mismatch in a finalized chunk is always an error.

```bash
nodrix recording info interrupted.ndrx
nodrix recording repair interrupted.ndrx --output recovered.ndrx
```

NDRX1 files remain readable. Repair and all new writes produce NDRX2.

## Reproducible run directory

Every unified run now contains:

- `resolved-plan.json` and redacted manifests;
- `nodrix.lock`;
- `events.jsonl`, metrics, status and result summaries;
- `environment.json` and `hardware.json`;
- `plugins.json` with resolved implementations and local SHA-256 hashes;
- `models.json` with model sizes and SHA-256 hashes.

These files describe the graph that was requested, the backends that actually
started, the machine on which it ran and the exact local code/model inputs
available to the runtime.
