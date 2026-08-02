# Nodrix 2.2.0-alpha.4 — Core Boundaries

This alpha fixes the architectural boundaries needed before adding more
integration providers. It is intentionally narrower than a domain-package or
new ROS transport release.

## Stable Core model

- `Edge` remains the logical connection between ports;
- an Edge without `transport` uses the local bounded Nodrix queue;
- `edges[].transport` delegates the physical/external path to a provider;
- generic `ManagedResource` and `ManagedApplication` contracts keep brokers,
  workspaces, processes, and external systems outside the hot data plane;
- `Session` remains a compatible specialized Resource throughout 2.x.

The Provider API adds `ResourceDescriptor`, `ApplicationDescriptor`, and
`TransportDescriptor`. These contracts contain no ROS-specific types and can
support DDS, Zenoh, MQTT, Kafka, databases, containers, or other integrations.

## Compatibility and YAML

Existing 2.x projects continue to load. The old `use` spelling and top-level
`links` are compatibility aliases; new files use `uses` and
`edges[].transport`. `nodrix validate --strict` reports the deprecated shape as
an error, and `nodrix migrate pipeline.yaml --to v2` rewrites it safely.

Compact YAML remains available for Nodes, Sessions, Resources, and
Applications, so provider parameters can still be written directly under an
entry. The resolved canonical document always places them in `parameters`.

`nodrix schema --output pipeline.schema.json` emits the maintained JSON Schema.
Both Core and provider-owned `nodrix init` templates now include the schema and
VS Code YAML mapping.

## Internal boundaries

The former large modules are compatibility facades over focused
implementations:

- manifest models, parsing, I/O, and schema generation;
- provider discovery, verification, loading, diagnostics, and templates;
- CLI context plus project, operation, catalog, and administration commands;
- runtime build, workers, execution, components, and integration lifecycle.

Characterization tests protect the established 2.x public imports while the
new modules use explicit dependencies rather than wildcard imports.

`NODRIX_PROVIDER_PATH` can restrict metadata discovery to explicit
distribution directories in hermetic development and CI runs. The modular
test script now creates its own temporary provider environment, so global
editable installs cannot contaminate the result.

## ROS 2 provider 0.4.0

`ros2.node`, `ros2.launch`, and `ros2.rviz` are managed Applications in new
templates. They no longer need artificial heartbeat messages to stay alive.
`ros2.topic` is an Edge Transport, so ROS-to-ROS payloads stay in DDS/RMW with
zero planned Nodrix copies. The old ROS process Nodes and `links` metadata stay
available for 2.x compatibility.

The generic `ros2` template is now separate from the Livox/FAST-LIVO2 example.
Both use one shared ROS session, canonical YAML, and explicit transported
Edges.

The release checks also install all independent wheels in a clean environment;
the Core sdist includes the public-API contract fixture required by its full
test suite.

## Deliberately deferred

This alpha does not add ROS services/actions/TF2, lifecycle-component support,
a native loaned-message bridge, or physically move media/vision/recording out
of the Core distribution. Those changes require their own package contracts
and qualification gates instead of being mixed into Core Boundaries.

Real Livox Mid-360S, FAST-LIVO2, RViz, RMW performance, and endurance checks
remain target-host validation on Ubuntu 24.04 with ROS 2 Jazzy.
