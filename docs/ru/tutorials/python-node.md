# Руководство: создание Python-узла

Создадим типизированный source, transform и sink через публичный facade `plyctl`.

## Структура

```text
python-sdk-demo/
├── pipeline.yaml
└── nodes/
    ├── __init__.py
    ├── source.py
    ├── transform.py
    └── sink.py
```

## Source

`nodes/source.py`:

```python
from plyctl import Message, SourceNode


class CounterSource(SourceNode):
    output_types = {"output": "core.object"}

    def produce(self):
        count = int(self.parameters.get("count", 5))
        for sequence in range(count):
            yield {
                "output": Message(
                    type="core.object",
                    payload={"value": sequence},
                    sequence=sequence,
                    metadata={"origin": "tutorial"},
                )
            }
```

Source возвращает mappings вида `имя_порта -> Message`.

## Transform

`nodes/transform.py`:

```python
from plyctl import Node, NodeContext


class MultiplyNode(Node):
    input_types = {"input": "core.object"}
    output_types = {"output": "core.object"}

    def open(self, context: NodeContext) -> None:
        super().open(context)
        self.factor = float(self.parameters.get("factor", 2))

    def process(self, inputs):
        message = inputs["input"]
        value = message.payload["value"] * self.factor
        return {
            "output": message.with_updates(
                payload={"value": value},
                metadata={**message.metadata, "factor": self.factor},
            )
        }
```

`Message` immutable. `with_updates()` создаёт новый envelope и сохраняет correlation-поля, если они не заменены явно. Payload сохраняется по ссылке, поэтому после публикации его нельзя изменять.

## Sink

`nodes/sink.py`:

```python
from plyctl import SinkNode


class ConsoleSink(SinkNode):
    input_types = {"input": "core.object"}

    def process(self, inputs):
        print(inputs["input"].payload)
        return None
```

## Manifest

```yaml
apiVersion: plyctl.dev/v2
kind: Pipeline
metadata: {name: python-sdk-demo}
runtime:
  mode: offline
  engine: unified
  type_validation: first
nodes:
  source:
    uses: ./nodes/source.py:CounterSource
    parameters: {count: 5}
  multiply:
    uses: ./nodes/transform.py:MultiplyNode
    parameters: {factor: 3}
  sink:
    uses: ./nodes/sink.py:ConsoleSink
edges:
  - from: source.output
    to: multiply.input
    queue: {capacity: 16, policy: block}
  - from: multiply.output
    to: sink.input
    queue: {capacity: 16, policy: block}
streams: {exports: []}
fragments: {}
recording: {}
security: {}
placement: {}
```

Поддерживается и обычная ссылка `my_package.nodes:MultiplyNode`.

## Проверка и запуск

```bash
plyctl validate pipeline.yaml
plyctl inspect pipeline.yaml
plyctl run pipeline.yaml
```

Ожидаемый вывод: `0`, `3`, `6`, `9`, `12`.

## Unit test

```python
from plyctl import Message
from nodes.transform import MultiplyNode


def test_multiply_node():
    node = MultiplyNode({"factor": 4})
    node.factor = 4
    result = node.process(
        {"input": Message(type="core.object", payload={"value": 5})}
    )
    assert result["output"].payload == {"value": 20}
```
