# Nodrix 1.0 data plane

## Placement-dependent path

```text
same executor             object/buffer handle
separate local process    shared-memory descriptor
separate host             typed wire protocol
same accelerator          DLPack or device handle
```

Device-only allocations are not serialised over a network or control pipe. Add an explicit download, converter, or encoder branch.

## Input pools

`SharedBufferPool` remains the staging path for ordinary CPU payloads entering an isolated node. Payloads already allocated from a shared pool cross by descriptor only.

## Output pools

Nodrix adds a separate reusable output pool:

```yaml
runtime:
  memory:
    shared_pool:
      block_size: 8388608
      capacity: 8
      threshold: 65536
    process_output_pool:
      block_size: 8388608
      capacity: 8
      threshold: 65536
```

An allocator-aware isolated node writes directly into this pool. Legacy outputs are copied once into a reserved slot when possible.

## Process source lifecycle

Each pull reserves output slots, invokes one `produce` iteration in the child, decodes descriptors, and releases unused slots. Used slots stay leased until downstream messages are destroyed or released.

## Memory planning

Each edge gets a static `MemoryPlan`. Run:

```bash
nodrix inspect --memory
```

The plan never hides a host/device transfer. Unsupported paths fail validation.

## Runtime report

`run.json` includes observed memory domains and bytes for every edge, plus input/output copy counts and both shared pools for isolated nodes.
