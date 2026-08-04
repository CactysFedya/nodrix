# Provider SDK reference

Provider contracts are defined in `nodrix.provider_api` in the 2.x distribution and are exported as stable public interfaces.

## Constants

```text
Provider API versions: "1", "2"
Preferred schemas: plyctl-provider/1, plyctl-provider/2
Compatibility schemas: nodrix-provider/1, nodrix-provider/2
Preferred entry-point group: plyctl.providers
Compatibility group: nodrix.providers
```

## `ProviderMetadata`

Required identity and compatibility fields:

```python
ProviderMetadata(
    id="vendor.integration",
    name="Vendor Integration",
    version="1.0.0",
    provider_api="2",
    requires_nodrix=">=2.3,<3",
    description="...",
    features=("nodes", "resources"),
    requires_features=(),
)
```

Provider IDs are lowercase dotted identifiers. `requires_nodrix` retains its field name for compatibility.

## Descriptors

### `NodeDescriptor`

Describes a lazily importable node:

```python
NodeDescriptor(
    id="vendor.node",
    factory="vendor.nodes:NodeClass",
    inputs={"input": "core.any"},
    outputs={"output": "core.any"},
    optional_inputs=(),
    features=(),
    parameters_schema={},
    bindings={},
    external_inputs={},
    external_outputs={},
)
```

### `SessionDescriptor`

Compatibility name for a pipeline-scoped connection/session.

### `ResourceDescriptor`

Preferred Provider API 2 name for a pipeline-scoped managed object that is not necessarily a connection.

### Managed applications and external links

Provider API 2 can describe executable applications, their factories, lifecycle/health behavior, and external ports. Use this for ROS 2 launch processes, device drivers, or existing services that should remain outside the in-process node graph.

## `ProviderRuntime`

A provider entry point returns a `ProviderRuntime` containing metadata and descriptor collections. Factories use `module:attribute` syntax and should not be imported during metadata-only compatibility checks.

## Feature negotiation

Providers declare features they offer and features they require. Runtime discovery rejects a provider when required capabilities are absent.

## Security

Production deployments should combine:

- provider allowlists;
- metadata signatures;
- an explicit trust store;
- package verification before installation;
- process isolation for untrusted native code.
