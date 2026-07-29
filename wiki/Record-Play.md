# Record and Play

Record any named streams into one universal file:

```bash
nodrix record /camera/frame /detector/detections --output experiment.ndrx
```

Inspect it:

```bash
nodrix recording info experiment.ndrx
```

Replay with original timing or as fast as possible:

```bash
nodrix play experiment.ndrx
nodrix play experiment.ndrx --speed 2
nodrix play experiment.ndrx --as-fast-as-possible
```

Pipeline nodes are also available:

```text
record.ndrx_source
record.ndrx_writer
```

The file preserves message type, sequence, timestamps, stream id, metadata, and
payload. Encoded media is stored without re-encoding.
