# Nodrix 1.5.0 multi-rate Vision example

```text
source 30 FPS ─┬─ latest → letterbox → NCNN detector ─┐
               └─ every frame ─────────────────────────▶ realtime ByteTrack
                                                          │
                                               tracks at source clock
                                                          │
                                               overlay → H.264 stream
```

Each implementation and its parameters live in one block YAML. The pipeline
contains graph structure, queue policy, stream exports and runtime metrics.

Place one NCNN `.param/.bin` model pair under
`models/yolo26n_ncnn_model/`, then:

```bash
nodrix validate
nodrix inspect
nodrix run
nodrix top
```

On another LAN computer:

```bash
nodrix stream list
nodrix-viewer /vision_production/preview/h264 --overlay
```

The encoder block probes hardware first and reports a visible software fallback
when the platform has no hardware encoder. Set `acceleration: required` for a
strict deployment. Host BGR frames remain an honest limitation of this example.

## Benchmark

The example source stops after 300 frames so variants terminate:

```bash
nodrix benchmark --spec benchmark.yaml
```

`native-tracker` and `python-tracker` compare the same algorithm with different
association backends. `strict-hardware-encoder` intentionally fails on a machine
without a working hardware encoder instead of hiding a software fallback.
