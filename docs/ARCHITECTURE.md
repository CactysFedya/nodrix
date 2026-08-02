# Nodrix architecture

## Product boundary

Nodrix Core is a generic typed streaming graph runtime. It does not require a
camera, detector, tracker, ROS 2, OpenCV, or a particular model runtime.

```text
Pipeline manifest
       ↓ validation
Executable graph
       ↓
Executor + queues + buffers + transports
```

Domain SDKs define payload contracts and reusable nodes:

```text
Nodrix Core
├── Nodrix Vision
├── nodrix-spatial
├── nodrix-mapping
├── nodrix-ros2
├── nodrix-spatial-ros2
├── Nodrix Audio      planned
└── user packages
```

## User terminology

| Term | Meaning |
|---|---|
| Pipeline | User-facing YAML description |
| Graph | Resolved executable structure |
| Node | Processing component |
| Port | Typed input or output |
| Edge | Logical connection between ports |
| Transport | Physical/local/external mechanism used by an Edge |
| Resource | Provider-owned dependency shared for one pipeline run |
| Session | 2.x-compatible specialized Resource |
| Application | Supervised external work outside the Nodrix data plane |
| Stream | Named output available to other processes/devices |
| Runtime | Graph executor and transport system |

A pipeline may be branched and is not limited to a linear chain.

## Core objects

### Message

A message contains:

```text
type
payload
sequence
timestamp_ns
created_ns
trace_id
stream_id
pipeline_id
run_id
source_id
metadata
```

The payload is retained by reference in the local graph.

### Node

`Node` is the only main processing API. Synchronous `process()` is the optimized
path. The executor inspects coroutine methods once when the worker starts;
synchronous nodes are called directly in the hot loop.

```text
SourceNode → Node → SinkNode
```

`SourceNode` and `SinkNode` are semantic specializations, not slower wrappers.

### Buffer

Large payloads may use a `ManagedBuffer` backed by:

- a NumPy/OpenCV allocation;
- a native aligned buffer pool;
- bytes or memoryview;
- a native plugin buffer.

Future device memory backends can implement the same handle model.

## Executor

The unified executor runs Python nodes and C++ processor/sink plugins in the
same graph.

```text
Python source
   ↓ native bounded queue
C++ plugin
   ↓ native bounded queue
Python sink
```

Each node has a worker. Local synchronous Python processing does not use
per-message asyncio scheduling. C++ plugin execution releases the GIL.

## Fan-out

One output can connect to multiple local edges and named network streams.

```text
                   ┌→ detector
camera.frame ──────┼→ recorder
                   └→ exported /camera/front/frame
```

The local consumers receive the same payload reference. Network serialization
is performed by an independent transport worker.

## Queue policies

Every edge and exported stream has its own bounded queue:

- `block`: preserve every message and apply backpressure;
- `latest`: retain only the newest value;
- `drop_oldest`: discard the oldest item when full;
- `drop_newest`: reject a new item when full.

Realtime video/telemetry preview normally uses `latest`. Offline dataset
processing normally uses `block`.

## Synchronization

Multi-input nodes support:

- `exact_sequence`;
- `approximate_timestamp`;
- `latest_available`;
- `zip`.

Example for a 30 FPS frame stream and a 10 FPS detector:

```yaml
synchronization:
  policy: latest_available
  trigger_port: frame
```

The node runs for every frame and receives the latest available detections.

## Local and distributed transport

### In-process edge

```text
Message reference → native bounded queue → consumer
```

No payload serialization and no payload copy.

### Named LAN stream

```text
producer worker
    ↓ enqueue reference
stream transport worker
    ↓ type-specific binary encoding
TCP peer connection
    ↓
remote runtime
```

The export worker is outside the producer's hot loop. On Unix, the sender uses
scatter/gather `sendmsg`, keeping large payload segments separate until the
kernel call.

## Discovery

A running pipeline advertises only explicitly exported streams.

```text
UDP multicast: name, type, host, endpoint, schema/codec metadata
TCP direct path: actual messages
```

There is no mandatory broker or agent. Each runtime participates directly in
LAN discovery. `nodrix stream list` sends a discovery query and collects
advertisements.

Nodrix joins multicast on all active IPv4 interfaces to support hosts that use
Wi-Fi and Ethernet simultaneously.

## Wire protocol

The fixed envelope contains:

```text
magic
wire version
sequence
timestamps
trace id
type name length
metadata length
payload length
```

Payload codecs are type-specific:

| Payload | Data path |
|---|---|
| bytes/buffer | raw contiguous bytes |
| Frame/Tensor | metadata + raw backing buffer |
| Detections/Tracks | packed NumPy array segments |
| generated type | fixed-layout struct bytes |
| control object | compact JSON fallback |

The transport does not force large data through JSON.

## Custom types

A YAML schema generates:

- a slotted Python dataclass;
- `struct.Struct` binary encoding;
- a packed C++20 struct;
- a registered local validator;
- a network wire codec;
- a machine-readable schema manifest.

Fixed layouts allow a C++ plugin to read the same bytes without field-by-field
conversion.

## Build model

Python graph:

```text
edit .py → nodrix run
```

C++ component:

```text
edit .cpp → build that plugin → nodrix run
```

There is no workspace-wide mandatory build or environment sourcing step.
An optional platform provider may manage its own workspace through a Session;
for example, `nodrix-ros2` prepares one colcon overlay per pipeline rather than
once per Node.

## Integration resources, applications, and transports

Provider API 2 keeps external systems out of the hot data plane:

```text
Provider Resource / Session
├── environment / connection pool / graph watcher
├── managed Applications
└── Edge Transports (DDS topics, broker routes, services)
```

An Edge is always the logical connection. Without an explicit `transport`, it
carries typed Nodrix messages through a bounded local queue. With a provider
Transport, it expresses external routing or remapping and appears in the
resolved plan with zero planned Nodrix copies. `Session` and top-level `links`
remain compatibility vocabulary through 2.x; new providers can use the generic
`Resource`, `Application`, and `Transport` contracts. None is tied to ROS 2.

## Intentional limitations after 0.6.0

- inter-process shared-memory streams are not yet the default transport;
- remote transport uses TCP rather than QUIC/RDMA;
- automatic certificate-based security is not included;
- native source plugins still use the fully native executor;
- LAN discovery requires multicast or an explicit `nodrix://` URI fallback;
- advanced ROS 2 loaned-message bridges, CUDA IPC, and DMA-BUF remain
  target-specific capabilities rather than implicit Core guarantees.

## Nodrix 0.8 data plane

### Transport hierarchy

The executor selects the least expensive valid path for each connection:

```text
same process       -> in-process reference / native bounded queue
different process  -> shared-memory descriptor + control IPC
different host     -> typed network stream
```

`execution.isolation: process` creates a process host around the normal `Node`
API. The user node does not implement IPC. Input and output messages still use
the same Nodrix type identifiers and wire codecs.

### Shared-memory ownership

`SharedBufferPool` preallocates a fixed number of equal-size blocks. Each block
is identified by a segment name, byte offset, size, and generation. When a
source allocates its payload directly from this pool, a process boundary sends
only the descriptor; the payload copy count is zero.

```text
SharedBufferPool block
    ├── source Message
    ├── local consumers
    └── isolated consumer mapping
```

A lease keeps the mapping alive until the final consumer releases the message.
Source-owned pools are closed only after all graph workers have drained and
stopped. Ordinary heap/NumPy payloads require one explicit staging copy when
entering shared memory; Nodrix counts that copy instead of calling it zero-copy.

### Process host and failures

```yaml
execution:
  isolation: process
  cpu_affinity: [2, 3]
failure:
  policy: restart
  max_restarts: 3
  backoff_ms: 100
```

The child process loads the same Python node class and communicates through a
small control pipe plus shared-memory descriptors for large payloads. Supported
policies are `stop_pipeline`, `restart`, and `skip_message`. Source nodes remain
in-process in 0.8.0 so device ownership and production ordering stay explicit.

### Universal recording

The `.ndrx` format stores normal Nodrix wire packets with an append-only stream
index. Consequently the recorder is independent of Vision, LiDAR, Audio, or a
specific user schema.

```text
file header
message records: arrival time + wire packet
stream/type index
footer with index offset
```

Already compressed `vision.encoded_frame` data is stored without media
re-encoding. Playback republishes the original type, sequence, timestamps,
stream id, metadata, and payload.

### Encoded media stream

`media.ffmpeg_encoder` is a persistent raw-frame-to-Annex-B node. Its H.264 or
H.265 output can fan out once to a file, an `.ndrx` recorder, and a named LAN
stream. `nodrix-viewer` keeps one persistent FFmpeg decoder and a latest-frame
mailbox, avoiding per-frame process startup and stale display queues.

## Device memory contract

Every port may declare accepted and preferred memory domains. `ManagedBuffer` can hold host storage, DLPack providers, DMA-BUF descriptors, CUDA IPC descriptors or backend-defined external handles. The executor creates a static memory plan and never silently inserts a CPU round-trip.

Process-isolated nodes and synchronous sources may allocate executor-owned shared outputs through `Node.allocate_output()`.
