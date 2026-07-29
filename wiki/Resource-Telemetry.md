# Per-node CPU and Memory Telemetry

```bash
nodrix top
nodrix top --interval 0.5
nodrix top --once
nodrix top --json
```

For process-isolated nodes Nodrix reads the node PID and reports exact process RSS/VMS, CPU percentage and thread count. Shared input/output pools are reported separately.

For in-process nodes the operating system exposes only one executor RSS. Nodrix therefore reports:

- the node's CPU share estimated from measured processing time;
- the shared executor RSS;
- estimated input-queue memory;
- buffer-pool and drop counters.

It does not invent per-node RSS values for objects shared in one process.

The same fields are available in `status.json`, `metrics.jsonl`, `/metrics.json`, Prometheus and final run reports.

Prometheus metrics include:

```text
nodrix_node_cpu_percent
nodrix_node_rss_bytes
nodrix_node_executor_rss_bytes
nodrix_node_shared_buffer_bytes
nodrix_node_estimated_queue_bytes
nodrix_system_memory_available_bytes
nodrix_system_temperature_c
```

On Linux/Raspberry Pi system telemetry also includes load average, available RAM and thermal-zone temperature when exposed by the kernel.
