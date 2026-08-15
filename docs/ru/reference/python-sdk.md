# Справочник Python SDK

Публичный facade:

```python
from plyctl import Message, Node, NodeContext, SourceNode, SinkNode
```

Compatibility imports из `nodrix` доступны в 2.x.

## `Message`

Immutable envelope:

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

- `with_updates(...)` создаёт изменённый message;
- `fork(...)` создаёт связанный message с parent/correlation;
- payload удерживается по ссылке и после emission не должен изменяться.

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

Compatibility lifecycle: `open`, `flush`, `close`. Новые методы адаптируются к ним.

## `SourceNode`

```python
class Source(SourceNode):
    output_types = {"output": "core.object"}

    def produce(self):
        yield {"output": Message(type="core.object", payload=1)}
```

## `SinkNode`

```python
class Sink(SinkNode):
    input_types = {"input": "core.object"}

    def process(self, inputs):
        consume(inputs["input"])
        return None
```

## `NodeContext`

Предоставляет node identity/configuration, runtime bindings и managed-buffer allocation через `allocate_buffer(...)`, если это допускает memory plan. Runtime-owned buffer нельзя сохранять за пределами lifecycle.

## Типы портов

```python
input_types = {"frame": "vision.frame"}
output_types = {"detections": "vision.detections"}
optional_inputs = {"calibration"}
```

## Ссылки на классы

```yaml
uses: ./nodes/custom.py:CustomNode
```

или:

```yaml
uses: my_package.custom:CustomNode
```
