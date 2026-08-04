# Providers and extension boundaries

A provider is an independently packaged integration that advertises capabilities before its Python implementation is imported.

## Why metadata-first discovery matters

Provider metadata allows Plyctl to check:

- provider identity and version;
- Provider API version;
- required Plyctl/Nodrix version range;
- required runtime features;
- node IDs, factories, ports, and parameter schemas;
- resources, sessions, managed applications, probes, and external links;
- signing and trust policy.

An incompatible provider can therefore be rejected without executing arbitrary import-time code.

## Provider APIs 1 and 2

Provider API 1 supports the original node and probe extension model. Provider API 2 adds transport-neutral managed resources, managed applications, richer external link descriptors, and feature negotiation.

New providers should use:

```text
schema: plyctl-provider/2
entry point group: plyctl.providers
provider_api: "2"
```

The `nodrix-provider/*` schemas and `nodrix.providers` entry-point group remain accepted during 2.x.

## When to use each extension mechanism

- Local Python class: one project, rapid iteration.
- Provider: reusable integration distributed as a Python package.
- Native plugin: hot path requiring C/C++ performance or ABI isolation.
- Managed application: existing executable, ROS 2 launch, driver, or service that should not be rewritten as a node.
