# Nodrix 1.6.0

Nodrix 1.6 introduces two explicit contracts: a deterministic execution plan
for the control plane and a pure C ABI for native data-plane plugins.

## Execution plan

```bash
nodrix inspect pipeline.yaml --plan
nodrix inspect pipeline.yaml --plan --output plan.json
```

`nodrix.execution-plan/v1` contains the redacted manifest hash, topological
order, resolved node implementation and device, synchronization policy,
resource limits, queues, memory transfers, expected copies, streams and
reproducibility warnings. The document has no timestamp, so identical inputs
produce identical bytes.

Every run writes the validated document to `resolved-plan.json` and adds actual
runtime backend information after nodes become ready.

## Plugin C ABI 2.0

Native plugins now include `nodrix/c_api.h` or the optional
`nodrix/cpp_plugin.hpp` convenience adapter. Only C-compatible sized
structures, opaque handles and callbacks cross the library boundary.

An owned `nodrix_buffer_v2` supplies thread-safe `retain` and `release`
callbacks. The host can therefore forward plugin and input buffers without a
payload copy while each side keeps its own allocator and runtime.

```bash
nodrix node create my-filter --language cpp
cmake -S nodes/my-filter -B nodes/my-filter/build
cmake --build nodes/my-filter/build
nodrix native inspect nodes/my-filter/build/libmy_filter.so
```

The previous ABI exposed a virtual C++ object and is intentionally not loaded.
External plugins execute in the unified runtime; the standalone native runner
continues only as a compatibility/performance tool for built-in `native.*`
nodes.
