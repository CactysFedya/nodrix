# Provider APIs 1 and 2

Provider APIs let an independently versioned Python distribution add Nodrix
Nodes, probes, templates, shared sessions, and external-link kinds without
changing or patching Core. API 1 remains supported; API 2 adds sessions and
external links.

## Security and loading order

Nodrix uses one fixed loading sequence:

```text
installed distribution discovery
→ read nodrix-provider.json without import
→ validate schema, API, version and declared features
→ verify nodrix-provider.sig and trust policy
→ import the nodrix.providers entry point
→ resolve only the selected Node or probe
```

`nodrix provider list` and `nodrix provider info` never import provider
packages. A provider cannot execute import-time code merely because it is
installed.

Each distribution declares exactly one entry point:

```toml
[project.entry-points."nodrix.providers"]
"example.echo" = "nodrix_example_provider:provider"
```

The entry-point name must equal `metadata.id`. A distribution containing
multiple Provider API 1 entry points, multiple metadata/signature files,
duplicate JSON keys, a mismatched version, or an unsupported schema is
rejected.

## Metadata

The wheel contains one `nodrix-provider.json` package-data file:

```json
{
  "schema": "nodrix-provider/1",
  "metadata": {
    "id": "example.echo",
    "name": "Example Echo Provider",
    "version": "1.0.0",
    "provider_api": "1",
    "requires_nodrix": ">=2.1,<3",
    "features": ["example.echo"],
    "requires_features": ["python-node-api.2"]
  },
  "nodes": [{
    "id": "example.echo",
    "factory": "nodrix_example_provider:EchoNode",
    "inputs": {"input": "core.any"},
    "outputs": {"output": "core.any"},
    "optional_inputs": [],
    "features": []
  }],
  "probes": [{
    "id": "example.echo.safe",
    "callable": "nodrix_example_provider:safe_probe",
    "depth": "safe",
    "timeout_seconds": 2.0,
    "permissions": [],
    "cooldown_seconds": 0.0
  }],
  "templates": []
}
```

The public SDK exports `ProviderMetadata`, `NodeDescriptor`,
`ProbeDescriptor`, `TemplateDescriptor`, `SessionDescriptor`,
`LinkDescriptor`, `ProviderManifest`, `ProviderRuntime`, and
`negotiate_features`.

The entry point may return `None` and use the manifest import references
directly, or return a `ProviderRuntime` with concrete Node classes and probe
callables. Runtime registrations may override only ids already declared in
metadata.

See `examples/provider_api` for a buildable external provider.

## Provider API 2

API 2 uses `schema: nodrix-provider/2` and `provider_api: "2"`. A session is a
pipeline-scoped resource shared by multiple Nodes; a link describes an
external path which creates no Nodrix queue and performs no Nodrix payload
copy. This general contract can support ROS 2, Zenoh, MQTT, Kafka, databases,
remote inference pools, or future transports.

```json
{
  "schema": "nodrix-provider/2",
  "metadata": {
    "id": "example.bus",
    "name": "Example Bus",
    "version": "1.0.0",
    "provider_api": "2",
    "requires_nodrix": ">=2.1,<3",
    "features": ["example.bus"],
    "requires_features": ["provider-sessions.1", "external-links.1"]
  },
  "nodes": [],
  "sessions": [{
    "id": "example.session",
    "factory": "example_bus:BusSession",
    "parameters_schema": {"type": "object"}
  }],
  "links": [{
    "id": "example.topic",
    "parameters_schema": {
      "type": "object",
      "required": ["topic"],
      "properties": {"topic": {"type": "string"}}
    }
  }]
}
```

Provider-owned templates are also available to the normal project generator:

```bash
nodrix init my-project --template provider-template-id
```

Template discovery and copying are metadata-first. Sources must remain inside
the installed provider package and symbolic links are rejected.

Development and hermetic test environments can restrict metadata discovery to
an explicit set of distribution directories with the platform-separated
`NODRIX_PROVIDER_PATH` environment variable. Imports still follow normal
Python rules; the override changes only which installed provider metadata is
considered and prevents unrelated global editable installs from leaking into a
test run.

## Signatures and trust

`nodrix-provider.sig` is a detached Ed25519 signature over canonical JSON
metadata. Generate it before building the wheel:

```python
from nodrix.providers import sign_provider_metadata

sign_provider_metadata(
    "nodrix_example_provider/nodrix-provider.json",
    "publisher-private.pem",
)
```

Trusted public keys are `.pem` files in:

```text
~/.config/nodrix/trust/providers/
```

Override that location with `NODRIX_PROVIDER_TRUST_STORE` or
`--trust-store`. Production provider ids must also be present in
`allowlist.json`:

```json
{"providers": ["example.echo"]}
```

Alternatively set a comma-separated `NODRIX_PROVIDER_ALLOWLIST` or repeat the
CLI `--allow` option. On POSIX, a production trust-store directory and its key
files must not be group/world-writable.

Development policy permits an unsigned provider while still enforcing schema,
API, version, feature negotiation, and runtime registration. Production policy
requires all of:

- compatible Provider API and Nodrix version;
- no missing Core features;
- detached Ed25519 signature;
- trusted public-key fingerprint;
- valid signature over the installed metadata;
- explicit production allowlist membership.

`nodrix run --production` verifies every external provider referenced by the
pipeline before importing any of them.

## CLI

```bash
nodrix provider list
nodrix provider list --json
nodrix provider info example.echo
nodrix provider verify example.echo
nodrix provider verify example.echo \
  --production \
  --trust-store /etc/nodrix/provider-keys \
  --allow example.echo
```

## Unified doctor

```bash
nodrix doctor
nodrix doctor --json
nodrix doctor --provider ros2
nodrix doctor --deep
```

Ordinary doctor runs only probes marked `depth: safe`. Deep probes are skipped
and cannot acquire a device until `--deep` is explicit. Every probe has a
timeout and declares its expected permissions. The JSON report uses schema
`nodrix-doctor/1` and includes Core/native/data-plane checks, provider trust
state, and probe evidence.

The previous `native doctor`, `device doctor`, `data-plane doctor`, and
`media doctor` commands remain available throughout the 2.x compatibility
line.

## Legacy adapter

Nodrix 2.1 exposes existing Core, Vision, Media, Recording, and ROS 2 Node ids
as internal Provider API records. The adapter preserves all 2.0 pipelines and
does not require signatures for implementations shipped inside the verified
Nodrix distribution. External providers cannot shadow an internal provider id.

The official Vision record also declares
`vision.ncnn_detector_native` with features `plugin-c-abi.2` and
`ncnn.native`. Unified Doctor reports whether its packaged platform library is
present without loading a model or acquiring a device.
