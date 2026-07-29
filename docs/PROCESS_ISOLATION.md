# Process isolation

## Processor or sink

```yaml
nodes:
  detector:
    uses: ./nodes/detector.py:Detector
    execution:
      isolation: process
      cpu_affinity: [2, 3]
      device: cuda:0
    failure:
      policy: restart
      max_restarts: 5
      backoff_ms: 500
```

The implementation remains a regular synchronous `Node`. Nodrix starts a spawned worker process and executes the normal lifecycle.

## Source

Nodrix 1.0 supports synchronous process-isolated `SourceNode` implementations:

```yaml
nodes:
  source:
    uses: ./nodes/source.py:Source
    execution:
      isolation: process
```

The source is pulled one message at a time by the executor. Async generators are still intended for the in-process compatibility path.

## Zero-copy output allocator

```python
class Source(SourceNode):
    output_types = {"output": "core.bytes"}
    output_memory = {"output": "shared"}

    def produce(self):
        buffer = self.allocate_output(1_048_576)
        device_or_algorithm_writes_into(buffer.memoryview())
        buffer.readonly = True
        yield {"output": Message(type="core.bytes", payload=buffer)}
```

The parent reserves a reusable shared block and sends its descriptor to the child. The child writes directly into the block. Returning the message transfers the lease to downstream consumers.

```text
input already shared         0 input copies
ordinary CPU input           1 staging copy
allocator-aware output       0 output copies
legacy ordinary CPU output   1 output copy
```

## Failure policies

- `stop_pipeline` — fail the graph;
- `restart` — spawn a new worker and retry;
- `skip_message` — omit the failed output when possible.

Nodes with external side effects should handle repeated sequence/trace IDs.

## Telemetry

```text
input_payload_copies
output_payload_copies
zero_copy_outputs
restarts
shared_input_pool
shared_output_pool
```
