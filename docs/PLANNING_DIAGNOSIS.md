# Planning, diagnosis, and tuning

## Static plan

```bash
nodrix plan pipeline.yaml
nodrix plan pipeline.yaml --json
nodrix plan pipeline.yaml --output plan.json
```

The plan contains the same deterministic execution and memory plan used by the
runtime, declared-rate propagation, hardware information, backend probes,
rejected alternatives, and recommendations.

Nodrix does not label a guessed rate as measured. A rate is shown only when it
can be derived from configured source frequency and explicit sampling. Unknown
processing capacity produces `expected_output_hz: null` and a benchmark
recommendation.

## Explain decisions

```bash
nodrix explain detector --pipeline pipeline.yaml
nodrix explain detector.backend --pipeline pipeline.yaml
nodrix explain edge source.frame:detector.frame --pipeline pipeline.yaml
nodrix explain detector.threads --pipeline pipeline.yaml
```

The output distinguishes the selected value, its source, the reason, and
rejected alternatives. Backend explanations use real probes when a safe
side-effect-free probe exists; otherwise they say that the final choice is made
when the node opens.

## Diagnose measurements

```bash
nodrix diagnose runs/RUN-ID
nodrix diagnose runs/RUN-ID/summary.json --json
nodrix diagnose pipeline.yaml --run
```

Diagnosis reads measured P95 processing time, queue depth/capacity, drops,
synchronization misses, payload copies, runtime fallback metadata, and
temperature. It does not execute a manifest unless `--run` is explicitly
supplied.

## Generate and evaluate tuning variants

```bash
nodrix optimize pipeline.yaml --output-dir tuning
nodrix optimize pipeline.yaml --output-dir tuning --benchmark \
  --latency-p95-ms 100 --temperature-c 75 --memory-mb 2048
```

The first command only writes `benchmark-variants.yaml` and
`optimization-plan.json`. The second evaluates those variants through the
normal reproducible benchmark engine and recommends the highest measured sink
throughput that satisfies every constraint.

The source pipeline is never changed. A recommendation contains
`applied: false`; promotion into production remains a deliberate review step.
