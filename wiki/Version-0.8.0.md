# Nodrix 0.8.0 Data Plane

Release highlights:

- fixed-block POSIX shared-memory pool;
- descriptor-only inputs to process-isolated nodes;
- process restart and skip policies;
- CPU affinity for isolated workers;
- universal indexed `.ndrx` record/play;
- persistent H.264/H.265 Nodrix encoder and Viewer decoder;
- live copy/restart/latency telemetry;
- `data-plane` project template;
- lifecycle-safe delayed resource closing.

Verification: 40 Python/integration tests and 1/1 native CTest passed.
