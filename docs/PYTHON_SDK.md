# Python SDK 2.x

The stable public imports are available directly from `nodrix`:

```python
from nodrix import Message, Node, NodeContext, SinkNode, SourceNode


class Scale(Node):
    input_types = {"input": "core.object"}
    output_types = {"output": "core.object"}

    def process(self, inputs):
        message = inputs["input"]
        return {
            "output": message.with_updates(
                payload={"value": message.payload["value"] * 2}
            )
        }
```

Manifest models, loaders, memory handles, lifecycle enums, registration helpers,
and the core error hierarchy are also public. Existing `open`, `flush`, and
`close` implementations are adapted to `configure`, `drain`, and `stop`.

`Message` preserves its payload by reference and carries stable correlation
fields: `pipeline_id`, `run_id`, `source_id`, `sequence`, `timestamp_ns`, and
`trace_id`.

Compute-heavy work should call a native library or use Plugin C ABI 2. Python is
the configuration and extension layer, not a mandatory copy stage for every
large payload.
