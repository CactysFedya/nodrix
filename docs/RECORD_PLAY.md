# Universal `.ndrx` record/play

## Record streams

```bash
nodrix record /camera/front/h264 /detector/detections \
  --output flight-01.ndrx --duration 120
```

`--count N` can stop after a total number of messages. Without a limit,
recording continues until interrupted.

## NDRX2 file structure

```text
NDRF v2 header
metadata JSON
NDC2 chunk header (counts, lengths, SHA-256)
  record 0: arrival time + Nodrix wire packet
  record 1: arrival time + Nodrix wire packet
  bounded chunk index
NDC2 chunk header
  ...
NDS2 final summary
NDF2 summary offset + SHA-256
```

The writer retains index entries only for the active checkpoint, 1024 records
by default. Each completed chunk is independently checksummed and durable
before the next chunk begins. Large wire payload parts are written directly;
the writer does not create another combined payload object.

An interrupted file is still readable:

- every completed checkpoint is verified and available;
- complete wire records in the unfinished chunk are recovered by scanning;
- a partial final record is ignored;
- checksum mismatches in finalized chunks are errors, not silent recovery.

`NdrxReader(..., recover=False)` requires a finalized recording. The default
`recover=True` exposes `recovered` and `finalized` in `recording info`.

NDRX1 files remain readable. New recordings always use NDRX2.

## Inspect and repair

```bash
nodrix recording info flight-01.ndrx
nodrix recording repair interrupted.ndrx --output recovered.ndrx
```

Repair copies every verified/recovered message into a finalized NDRX2 file and
records the source path and source format in metadata. It never overwrites the
source file.

## Replay

```bash
nodrix play flight-01.ndrx
nodrix play flight-01.ndrx --speed 0.5
nodrix play flight-01.ndrx --speed 2
nodrix play flight-01.ndrx --as-fast-as-possible
nodrix play flight-01.ndrx --prefix /replay
nodrix play flight-01.ndrx --start 1000 --count 300 --fixed-fps 30
```

Playback starts a normal Nodrix stream publisher. A short startup delay allows
subscribers to discover and connect before the first record.
`--start` performs an indexed message seek; `--count 1` is a scriptable
single-step primitive.

## Pipeline nodes

Record inside a graph:

```yaml
recorder:
  uses: record.ndrx_writer
  parameters:
    path: outputs/experiment.ndrx
    checkpoint_records: 1024
    durable: true
```

Replay into a graph:

```yaml
source:
  uses: record.ndrx_source
  parameters:
    path: data/experiment.ndrx
    speed: 1.0
    start: 0
    fixed_fps: 0
```

The source output is `core.any`, so the original message type remains attached
to every message and is validated by downstream ports.
