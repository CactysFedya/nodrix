# Nodrix Benchmarking

For guided variant generation and constraint-aware selection, see
`PLANNING_DIAGNOSIS.md` or run:

```bash
nodrix optimize pipeline.yaml --benchmark --latency-p95-ms 100
```

This uses the benchmark engine described below and never modifies the source
pipeline.

Nodrix 1.4.0 replaces the earlier repeat-only benchmark helper with a versioned benchmark suite.

## Direct benchmark

```bash
nodrix benchmark pipeline.yaml --warmup 1 --repeat 3
```

The command creates:

```text
.nodrix/benchmarks/<suite-id>/
├── benchmark.json
├── environment.json
├── models.json
└── variants/
    └── default/
        ├── summary.json
        ├── warmup/
        └── runs/
```

Every measured run remains a complete Nodrix run artifact. Warm-up runs are stored separately and are never included in the measured aggregate.

## Variant specification

```yaml
version: 1
pipeline: pipeline.yaml
warmup: 1
repeat: 3
variants:
  fast:
    profile: maximum-throughput
    set:
      - detector.imgsz=320
  accurate:
    profile: realtime-balanced
    block:
      - detector=blocks/detectors/yolo512.yaml
```

Run every variant:

```bash
nodrix benchmark --spec benchmark.yaml
```

Run selected variants:

```bash
nodrix benchmark --spec benchmark.yaml --variant fast
```

## Metrics

The benchmark aggregate contains:

- duration mean/min/max/P50/P95/P99;
- conservative source and terminal-sink rate;
- pipeline end-to-end P95;
- queue drops and node errors;
- estimated node/process/shared/queue memory;
- temperature when available;
- per-node processing, queue-wait, end-to-end and rate distributions.

The memory value is an estimate from observable runtime scopes. In-process per-node RSS is not claimed to be exact.

## Reproducibility

The suite stores the active `NODRIX_*` environment variables after secret filtering and SHA-256 hashes for local model files discoverable from the pipeline and imported blocks.

## Replay gate

```bash
nodrix replay <run-id>
```

A run is directly replayable when a `.ndrx` recording exists in its artifacts. Runs backed only by RTSP/HTTP/SRT or camera sources are reported as non-replayable until the input is recorded. Manifest-only replay is allowed as a best-effort path and may still require the original project directory for relative assets.
