# Nodrix 0.5.0 — Universal Graph and LAN Streams

## Breaking changes

- Project renamed to **Nodrix**.
- Only the `nodrix` CLI is installed.
- `visionpipe` and `vpipe` commands are removed.
- Python package is `nodrix`.
- `FastNode`, `FastSourceNode`, and `FastSinkNode` are removed.
- `Node`, `SourceNode`, and `SinkNode` are the optimized APIs.
- C++ plugin namespace changed to `nodrix`.
- Plugin ABI is now version 2.

## Project creation

`nodrix init` now creates a complete project with working implementations,
tests, configuration, a custom type schema, and a buildable C++ plugin example.

Templates:

```text
core
vision
network
benchmark
```

## Universal core and Vision SDK

Core imports:

```python
from nodrix import Message, Node, SourceNode, SinkNode
```

Vision imports:

```python
from nodrix.vision import Frame, Tensor, Detections, Tracks
```

## Distributed streams

- explicit stream exports in `pipeline.yaml`;
- automatic multicast LAN discovery;
- discovery on all active IPv4 interfaces;
- direct publisher-to-subscriber TCP data path;
- no mandatory agent or broker;
- subscription by name or explicit `nodrix://` URI;
- `nodrix stream list`, `info`, and `echo`;
- `core.stream_source` for remote data inside a graph;
- independent native bounded queue per export and client;
- background serialization/fan-out;
- Unix scatter/gather sending.

## Generic wire protocol

Supports raw buffers, frames, tensors, detection/tracking arrays, control
objects, and registered custom codecs.

## User-defined types

`nodrix type build` generates:

- a slotted Python dataclass;
- a binary Python codec;
- a packed C++20 struct;
- a schema manifest;
- automatic local and network registration.

Generated types were verified through Python → C++ plugin → Python.

## Runtime optimization

- direct synchronous `Node.process()` call in the hot loop;
- no separate `FastNode` abstraction;
- network work moved outside producer threads;
- no serialization when an exported stream has no subscribers;
- local payload fan-out remains zero-copy.

## Tests and verification

- 20 Python/integration tests passed;
- native extensions built successfully;
- C++20 core test passed;
- four project templates validated;
- core generated project executed;
- zero-configuration publisher/subscriber scenario executed;
- mixed Python/C++ graph passed ABI 2;
- generated custom type compiled and crossed Python/C++ boundaries.

## Known boundaries

- inter-process shared memory is not yet used automatically;
- network transport is TCP in 0.5.0;
- discovery depends on multicast unless an explicit URI is used;
- no built-in authentication/encryption layer yet;
- native sources remain part of the fully native executor;
- ROS 2 bridge and record/play are not included.
