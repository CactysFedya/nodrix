# Руководство: создание provider

Provider распространяет переиспользуемые nodes, probes, resources и managed applications без изменения ядра Plyctl.

## Структура пакета

```text
example-provider/
├── pyproject.toml
└── src/example_provider/
    ├── __init__.py
    ├── nodes.py
    └── plyctl-provider.json
```

## Entry point

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "example-plyctl-provider"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["plyctl>=2.3.0a1,<3"]

[project.entry-points."plyctl.providers"]
"example.echo" = "example_provider:provider"
```

Старая группа `nodrix.providers` поддерживается, но новые provider должны использовать `plyctl.providers`.

## Узел

`nodes.py`:

```python
from plyctl import Node


class EchoNode(Node):
    input_types = {"input": "core.any"}
    output_types = {"output": "core.any"}

    def process(self, inputs):
        return {"output": inputs["input"]}
```

## Provider runtime

`__init__.py`:

```python
from nodrix.provider_api import NodeDescriptor, ProviderMetadata, ProviderRuntime


def provider() -> ProviderRuntime:
    return ProviderRuntime(
        metadata=ProviderMetadata(
            id="example.echo",
            name="Example Echo Provider",
            version="0.1.0",
            provider_api="2",
            requires_nodrix=">=2.3,<3",
            features=("nodes",),
        ),
        nodes=(
            NodeDescriptor(
                id="example.echo",
                factory="example_provider.nodes:EchoNode",
                inputs={"input": "core.any"},
                outputs={"output": "core.any"},
            ),
        ),
    )
```

Контракты Provider API в серии 2.x находятся в `nodrix.provider_api` как стабильный compatibility API.

## Metadata-first descriptor

`plyctl-provider.json`:

```json
{
  "schema": "plyctl-provider/2",
  "id": "example.echo",
  "name": "Example Echo Provider",
  "version": "0.1.0",
  "provider_api": "2",
  "requires_nodrix": ">=2.3,<3",
  "features": ["nodes"],
  "nodes": [
    {
      "id": "example.echo",
      "factory": "example_provider.nodes:EchoNode",
      "inputs": {"input": "core.any"},
      "outputs": {"output": "core.any"}
    }
  ]
}
```

Plyctl может проверить совместимость metadata до импорта кода provider.

## Установка и диагностика

```bash
python -m pip install -e .
plyctl provider list
plyctl provider info example.echo
plyctl provider doctor example.echo
```

Точные параметры всегда проверяйте через `plyctl provider --help` в текущем commit.

## Использование

```yaml
nodes:
  echo:
    uses: example.echo
```
