# Universal `.ndrx` record/play

## Record streams

```bash
nodrix record /camera/front/h264 /detector/detections \
  --output flight-01.ndrx --duration 120
```

`--count N` can stop after a total number of messages. Without a limit, recording continues until interrupted.

## File structure

```text
NDRF header
metadata JSON
record 0: arrival time + Nodrix wire packet
record 1: arrival time + Nodrix wire packet
...
NDXI index
NDXF footer with index offset
```

The indexed table includes:

```text
file offset
arrival monotonic timestamp
stream id
message type
sequence
timestamp_ns
wire packet size
```

Large wire payload parts are written sequentially into the file. The writer does not construct another combined Python payload object.

## Inspect

```bash
nodrix recording info flight-01.ndrx
```

## Replay

```bash
nodrix play flight-01.ndrx
nodrix play flight-01.ndrx --speed 0.5
nodrix play flight-01.ndrx --speed 2
nodrix play flight-01.ndrx --as-fast-as-possible
nodrix play flight-01.ndrx --prefix /replay
```

Playback starts a normal Nodrix stream publisher. A short startup delay allows LAN subscribers to discover and connect before the first record.

## Pipeline nodes

Record inside a graph:

```yaml
recorder:
  uses: record.ndrx_writer
  parameters:
    path: outputs/experiment.ndrx
```

Replay into a graph:

```yaml
source:
  uses: record.ndrx_source
  parameters:
    path: data/experiment.ndrx
    speed: 1.0
```

The source output is `core.any`, so the original message type remains attached to every message and is validated by downstream ports.
