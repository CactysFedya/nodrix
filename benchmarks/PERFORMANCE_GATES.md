# Performance release gates

Hosted CI runs a conservative native-graph smoke gate. Release qualification
uses the same dedicated machine for the baseline and candidate:

```bash
python scripts/check_performance.py \
  benchmark-baseline.json benchmark-candidate.json
```

The default limits are:

- throughput regression: at most 10%;
- P95 latency regression: at most 15%;
- unexpected payload copies: zero;
- post-warm-up memory growth: no more than the scenario allowance.

Input files use this stable shape:

```json
{
  "scenarios": {
    "native-64k": {
      "throughput": 125000,
      "p95_ms": 0.08,
      "unexpected_copies": 0,
      "memory_growth_bytes": 0,
      "max_memory_growth_bytes": 1048576
    }
  }
}
```

Do not compare absolute results from different hosted runners. Raspberry Pi 5,
Jetson, and GPU-workstation baselines are retained per physical release host.
