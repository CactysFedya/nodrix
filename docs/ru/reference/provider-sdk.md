# Справочник Provider SDK

Stable contracts находятся в `nodrix.provider_api` в distribution 2.x.

## Версии и имена

```text
Provider API: "1", "2"
Новые schemas: plyctl-provider/1, plyctl-provider/2
Compatibility schemas: nodrix-provider/1, nodrix-provider/2
Новая entry-point group: plyctl.providers
Compatibility group: nodrix.providers
```

## `ProviderMetadata`

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

Provider ID — lowercase dotted identifier. Поле `requires_nodrix` сохраняет compatibility name.

## `NodeDescriptor`

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

## Resources и applications

- `SessionDescriptor` — compatibility name для pipeline-scoped session.
- `ResourceDescriptor` — предпочтительное transport-neutral имя API 2.
- Managed applications описывают внешние executables, lifecycle, health и external ports.

## `ProviderRuntime`

Entry point возвращает `ProviderRuntime` с metadata и collections descriptors. Factory задаётся как `module:attribute` и не должна импортироваться при metadata-only проверке.

## Security

Для production:

- allowlist provider;
- metadata signatures;
- explicit trust store;
- verify package до install;
- process isolation для untrusted native code.
