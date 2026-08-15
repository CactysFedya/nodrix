# Tutorial: create a provider

A provider distributes discoverable nodes, probes, resources, and managed applications without modifying Plyctl core.

## 1. Create a package

```text
example-provider/
├── pyproject.toml
└── src/example_provider/
    ├── __init__.py
    ├── nodes.py
    └── plyctl-provider.json
```

## 2. Register the entry point

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

The legacy `nodrix.providers` group remains accepted, but new providers should use `plyctl.providers`.

## 3. Implement a node

`src/example_provider/nodes.py`:

```python
from plyctl import Node


class EchoNode(Node):
    input_types = {"input": "core.any"}
    output_types = {"output": "core.any"}

    def process(self, inputs):
        return {"output": inputs["input"]}
```

## 4. Export the runtime

`src/example_provider/__init__.py`:

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
            description="Tutorial provider",
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

The provider contracts currently live in `nodrix.provider_api` for 2.x compatibility. They are part of the stable public API exported by the distribution.

## 5. Add metadata-first discovery

`src/example_provider/plyctl-provider.json`:

```json
{
  "schema": "plyctl-provider/2",
  "id": "example.echo",
  "name": "Example Echo Provider",
  "version": "0.1.0",
  "provider_api": "2",
  "requires_nodrix": ">=2.3,<3",
  "description": "Tutorial provider",
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

Metadata-first discovery lets Plyctl reject incompatible packages before importing provider code.

## 6. Install and inspect

```bash
python -m pip install -e .
plyctl provider list
plyctl provider info example.echo
plyctl provider doctor example.echo
```

Use `plyctl --help` and `plyctl provider --help` as the source of truth for available options in the checked-out commit.

## 7. Use the provider node

```yaml
nodes:
  echo:
    uses: example.echo
```

Then validate the consuming pipeline before running it:

```bash
plyctl validate pipeline.yaml
plyctl inspect pipeline.yaml
```
