# System interfaces and bindings

Nodrix 2.21 makes a nested System a typed component. A parent configures only
the child's public parameters, resources, inputs, and outputs; the child keeps
its own Definition revision, Plan, execution context, lifecycle, and Run
boundary.

```text
parent description
  → child public contract
    → explicit bindings
      → recursively resolved backend endpoints
```

The planner resolves this chain before execution. It never copies child nodes
into the parent graph.

## Complete YAML example

```yaml
apiVersion: nodrix.system/v1       # Stable System document contract.
kind: System                       # This document is a System Definition.
name: mapping-stack                # Independently versioned Definition name.

inputs:                            # Typed values accepted from the parent.
  - name: control                  # Public input port name.
    type_id: mapping.control/v1    # Backend-neutral message contract.

outputs:                           # Typed values exposed to the parent.
  - name: map
    type_id: spatial.metric_map/v1

parameters:                        # Portable per-instance configuration.
  - name: voxel_size
    type: number                   # any|string|integer|number|boolean|object|array
    default: 0.2                   # Used when the parent does not override it.
    description: Mapping leaf size in metres.

resourceRequirements:             # Resources supplied through this boundary.
  - name: lidar
    uses: livox.device             # Required ResourceDefinition identity.
    optional: false

resources:                         # Internal realization of the requirement.
  - name: internal_lidar
    uses: livox.device

systems:                           # Child Definitions remain independent.
  - name: driver                   # LiDAR driver instance role.
    uses: ./driver.yaml
    resources:
      lidar: internal_lidar        # Child requirement → parent ResourceInstance.
  - name: mapper                   # Instance role in this parent.
    uses: ./mapper.yaml            # Resolved and pinned to an exact revision.

bindings:                          # Public contract → internal implementation.
  inputs:
    - port: control
      endpoint: system:mapper.control # application.port | graph/node.port | system:child.port
  outputs:
    - port: map
      endpoint: system:mapper.map
  parameters:
    - parameter: voxel_size
      targets:
        - system:mapper.voxel_size # Public parent parameter → child parameter.
  resources:
    - resource: lidar
      instance: internal_lidar

links:                             # Connections between independently planned parts.
  - from: system:driver.cloud      # A child public output.
    to: system:mapper.cloud        # A child public input.
    uses: ros2.topic               # Required when LocalBackend crosses runtimes.
    parameters:
      topic: /livox/lidar
```

## Endpoint and parameter syntax

Port endpoints have three canonical forms:

- `application.port` for an `ApplicationInstance`;
- `graph/node.port` for a node inside a Graph;
- `system:instance.port` for a nested System public port.

Parameter targets are deliberately explicit:

- `application:name.parameter`;
- `resource:name.parameter`;
- `system:name.parameter`;
- `node:graph/name.parameter`.

A public parameter may fan out to several internal targets. An internal target
cannot also contain an explicit instance value, and cannot be bound twice.
When an SDK catalog is available, Nodrix validates the portable System type
against the Python SDK annotation before planning.

## Parameters, context, and resources

These channels have different semantics:

- `SystemInstance.parameters` are declarative, portable values copied into the
  exact Plan and injected only into declared parameter targets;
- `SystemExecutionContext.systems` contains operational overrides such as
  environment variables and runtime defaults. A child inherits its parent and
  consumes only its named override branch. Plans store the context digest, not
  secret values;
- `SystemInstance.resources` maps a child requirement to a parent
  `ResourceInstance`. The compiled binding carries the exact provider
  configuration and placement to a backend that advertises
  `system_resources`.

Direct resource injection cannot cross a target or backend. Use an explicit
service/application boundary for a remote resource.

## Links and runtime boundaries

The planner resolves a System link through any number of nested public
bindings to the final graph/application endpoints. Each child still receives
its own backend context and lifecycle handle.

A backend must advertise `system_interfaces`. LocalBackend lowers an explicit
transport-backed child link into the existing integration-provider contract.
It rejects an implicit in-memory link between independent child runtimes with
`LOCAL103`; silently flattening the children would change lifecycle and
resource ownership semantics.

Use `uses` for every LocalBackend child-runtime link and for every
cross-target/backend link. Cross-target/backend execution itself remains
outside the local 3.0 release boundary.

## Planning and inspection

```bash
plyctl system validate systems/mapping-stack.yaml --project .
plyctl system plan systems/mapping-stack.yaml --project . --explain
plyctl system plan systems/mapping-stack.yaml --project . --json
```

`--explain` prints recursively resolved IN/OUT/PAR/RES bindings. JSON includes
the same contracts and effective values in `inputs`, `outputs`, `parameters`,
`resource_requirements`, `bindings`, and each child Plan.

Important stable diagnostics include `SYS171`–`SYS180` for child values and
SDK parameter bindings, `PLAN407`–`PLAN413` for compiled interface failures,
`BACKEND104`/`BACKEND105` for unsupported resource/interface capabilities, and
`LOCAL103` for a missing LocalBackend transport.

## Python SDK

```python
from nodrix import (
    SystemBoundaryBindings,
    SystemParameter,
    SystemParameterBinding,
    SystemPort,
    SystemPortBinding,
    SystemResourceBinding,
    SystemResourceRequirement,
)

parameters = (
    SystemParameter(name="voxel_size", type="number", default=0.2),
)
bindings = SystemBoundaryBindings(
    inputs=(
        SystemPortBinding(port="control", endpoint="system:mapper.control"),
    ),
    parameters=(
        SystemParameterBinding(
            parameter="voxel_size",
            targets=("system:mapper.voxel_size",),
        ),
    ),
)
```
