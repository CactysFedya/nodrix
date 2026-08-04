# Python SDK reference

Use the public facade:

```python
from plyctl import Message, Node, NodeContext, SourceNode, SinkNode
```

The compatibility `nodrix` imports remain available in 2.x.

## `Message`

`Message` is an immutable envelope. Important fields include:

```python
Message(
    type="core.object",
    payload={"value": 1},
    sequence=0,
    timestamp_ns=None,
    source_timestamp_ns=None,
    correlation_id=None,
    parent_id=None,
    metadata={"sensor": "demo"},
)
```

Methods:

- `with_updates(...)`: create a modified message while preserving unspecified correlation fields;
- `fork(...)`: create a related message with parent/correlation information.

Payload objects are retained by reference. Do not mutate them after publishing unless the data type contract explicitly allows mutation.

## `Node`

```python
class Node:
    input_types: dict[str, str]
    output_types: dict[str, str]
    optional_inputs: set[str]

    def configure(self, context: NodeContext) -> None: ...
    def start(self) -> None: ...
    def process(self, inputs): ...
    def drain(self) -> None: ...
    def stop(self) -> None: ...
```

Compatibility methods remain part of the adapted lifecycle:

```python
def open(self, context): ...
def flush(self): ...
def close(self): ...
```

`configure`, `drain`, and `stop` adapt to `open`, `flush`, and `close` respectively.

## `SourceNode`

Implement `produce()` and yield port-to-message mappings:

```python
class Source(SourceNode):
    output_types = {"output": "core.object"}

    def produce(self):
        yield {"output": Message(type="core.object", payload=1)}
```

## `SinkNode`

A sink normally returns `None`:

```python
class Sink(SinkNode):
    input_types = {"input": "core.object"}

    def process(self, inputs):
        consume(inputs["input"])
        return None
```

## `NodeContext`

The context provides runtime services and bindings. Public behavior includes access to node identity/configuration, runtime bindings, and managed-buffer allocation through `allocate_buffer(...)` when the selected runtime memory plan supports it.

Do not retain a context or runtime-owned buffer beyond its documented lifecycle.

## Type declarations

Declare ports on the class:

```python
input_types = {"frame": "vision.frame"}
output_types = {"detections": "vision.detections"}
optional_inputs = {"calibration"}
```

Validation can then reject invalid edges before execution.

## Local references

```yaml
uses: ./nodes/custom.py:CustomNode
```

or:

```yaml
uses: my_package.custom:CustomNode
```
