# Nodrix performance model

## Priority order

Nodrix optimizes the data path in this order:

1. avoid payload copies;
2. keep queues bounded;
3. isolate slow branches;
4. avoid per-message asyncio scheduling;
5. execute compute-heavy work in native libraries or C++ plugins;
6. measure queue, processing, and end-to-end latency separately.

## Python nodes

`Node.process()` is the fast Python API. For a synchronous node, the executor
stores the bound method and calls it directly. Async compatibility exists, but
is not used in the synchronous hot loop.

For CPU-heavy algorithms, prefer:

- NumPy/OpenCV vectorization;
- ONNX Runtime/NCNN/OpenVINO/TensorRT calls;
- a focused C++ extension;
- a Nodrix C++ plugin.

## Local queues

The installed native extension implements bounded queues in C++. Blocking waits
release the GIL. Queue policy is selected per edge.

Avoid large `block` queues in realtime graphs. They increase stale end-to-end
latency even when no messages are lost.

## Buffers

The native buffer pool provides aligned reusable allocations. `Frame` and
`Tensor` wrap existing contiguous NumPy/OpenCV storage without an implicit copy.

A fan-out sends references to one payload:

```text
one frame allocation
├── detector reference
├── recorder reference
└── transport reference
```

## Network export

The producer thread only enqueues a message reference. A transport worker:

1. selects the type codec;
2. creates a small header and metadata block;
3. retains views over large payload segments;
4. sends them using scatter/gather where available.

This prevents a preview subscriber from adding JPEG/TCP work to the detector
worker unless the graph explicitly places an encoder node in that branch.

## Custom types

Generated fixed-layout types use `struct.Struct` in Python and a packed C++
struct with the same byte size. They do not use JSON in the data path.

## Release verification samples

The following are local verification samples from the release build container,
not universal hardware claims.

### Three-node Python graph

```text
100,000 messages
Source → Multiply → JSONL Sink
mean pipeline duration: approximately 1.58 s
approximately 63,000 messages/s
```

The JSONL sink performs real file output, so this is not a queue-only number.

### Loopback stream transport

```text
400 messages × 512 KiB = 200 MiB
TCP loopback, block policy
approximately 4.28 GiB/s observed
```

Loopback measures memory/kernel transport on one machine. Physical Ethernet or
Wi-Fi throughput will be limited by the network, codec, CPU, and payload format.

### Native plugin

The release conformance graph runs external C ABI source → processor →
processor → sink in the standalone C++ runner. Normal CI validates 100,000
messages and exact correlation/ownership; the stress job validates one million
messages without retained plugin buffers.

## Measuring your graph

```bash
nodrix benchmark --warmup 2 --repeat 5
```

Run reports include:

- message count and rate;
- processing P50/P95/P99;
- queue-wait P50/P95/P99;
- end-to-end P50/P95/P99;
- dropped messages and maximum queue depth;
- exported stream queue and send counters.

Dedicated same-host regression comparison is documented in
`benchmarks/PERFORMANCE_GATES.md`. The gate rejects throughput loss above 10%,
P95 growth above 15%, unexpected copies, and memory growth beyond the scenario
allowance.

## Remaining performance work

Planned improvements:

- inter-process shared-memory rings;
- fixed binary metadata for standard types;
- native network reactor and batching;
- QUIC/UDP transports for best-effort realtime data;
- hardware-specific CUDA IPC and DMA-BUF import/export operators;
- CPU affinity and executor pools;
- explicit deadline telemetry.

## 0.8 process and shared-memory copy matrix

| Producer payload | Consumer placement | Payload copies before consumer |
|---|---|---:|
| `SharedBufferPool` block | same process | 0 |
| `SharedBufferPool` block | isolated process | 0 |
| ordinary contiguous CPU buffer | same process | 0 |
| ordinary contiguous CPU buffer | isolated process | 1 staging copy |
| any payload | another host | at least one kernel/network transfer |

A process boundary is not automatically zero-copy. Zero-copy requires that the
producer allocate the payload in shareable storage from the start. Nodrix
exposes `input_payload_copies` and `output_payload_copies` separately in live
telemetry so this distinction is visible.

### Shared-pool sizing

Choose `block_size` for the largest expected payload and keep `capacity` small
but sufficient for all simultaneous consumers and queue slots:

```yaml
runtime:
  memory:
    shared_pool:
      block_size: 2764800   # 1280x720 BGR8
      capacity: 8
      threshold: 65536
```

Too few blocks causes producer waits. Too many blocks waste resident shared
memory. `nodrix inspect --live` reports message rate, latency, input/output
copies, restarts, and the run report includes shared-pool acquisitions, reuse,
waits, and peak usage.

### Process isolation trade-off

Isolation improves fault containment and can bypass Python GIL contention
between CPU-bound nodes, but it adds control IPC and lifecycle overhead. Keep
very small stateless nodes in-process. Isolate expensive, unstable, or
independently restartable components.

### `.ndrx` recording

The NDRX2 recorder writes message headers and payload segments directly in
arrival order and checkpoints bounded indexes throughout the run. Encoded
H.264/H.265 payloads are not decoded or re-encoded. For raw frames, storage
bandwidth remains the limiting factor; record an encoded branch when raw
fidelity is unnecessary.
