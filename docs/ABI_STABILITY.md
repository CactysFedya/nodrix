# Plugin C ABI 2.0

The official ABI value is `0x00020000` (`131072`). A plugin exports:

```text
nodrix_plugin_abi_version_v2
nodrix_plugin_features_v2
nodrix_plugin_create_v2
```

The complete interface is in `nodrix/c_api.h`. The shared-library boundary
contains only fixed-width integers, byte spans, function pointers and opaque
handles. It never contains:

- a C++ standard-library type;
- a virtual C++ object;
- an exception or RTTI object;
- ownership that must be released by a different allocator.

Every public structure begins with `struct_size`. A node is represented by an
opaque `instance` and a function table. Every operation returns a
`nodrix_status_v2`; an optional `last_error` string remains owned by the
plugin.

Hosts and plugins validate the documented `*_REQUIRED_SIZE` prefix, accept
larger structures, ignore unknown trailing fields, and zero-initialize output
structures. Adding a trailing field therefore does not require an ABI number
change. Removing, reordering, or changing an existing field does.

## Correlation strings

`nodrix_message_v2.correlation` preserves `pipeline_id`, `run_id`,
`source_id`, `stream_id`, `trace_id`, and `span_id`. The trace flag
distinguishes an integer trace identifier from a textual one.

Every `nodrix_string_view_v2` is borrowed:

- an input view remains valid until `process()` returns;
- an emitted view must remain valid until the synchronous `emit()` callback
  returns;
- empty values use `size == 0`; `data` may be null;
- a consumer that needs a longer lifetime copies the bytes;
- plugins must not retain a string pointer because strings have no
  `retain/release` callback.

## Buffers

`nodrix_buffer_v2` carries a byte span and optional `retain`/`release`
callbacks. If both callbacks are present, the host retains the buffer and
passes it through without copying. A buffer without ownership callbacks is
borrowed only for the current call; the host copies it if the plugin emits it.
Callbacks must be thread-safe and must not throw.

`nodrix_memory_handle_v2` carries an opaque matching-domain device allocation.
The owner callbacks apply to the allocation/handle and follow the same
retain/release rule. Device-only buffers leave `data` null. Nodrix does not
interpret a CUDA, DMA-BUF, Vulkan, Metal, or DLPack handle as a host pointer.
Ports must use one of `any`, `cpu`, `pinned_cpu`, `shared`, `dma_buf`, `cuda`,
`rocm`, `vulkan`, `opencl`, `metal`, `npu`, `dlpack`, or `external`.

## Lifecycle

For every successfully created node the host calls:

```text
open → process/run source → flush → close → destroy
```

`destroy` is called exactly once. Libraries remain loaded until their last node
and retained buffer are destroyed. The optional context callback lets long
running sources cooperatively observe shutdown. No C++ exception may cross an
exported C function; the C++ convenience wrapper converts exceptions to
`NODRIX_STATUS_RUNTIME_ERROR`.

## Inspection and execution

```bash
nodrix native inspect libplugin.so
```

External plugins run in either the unified control plane or the pure native
data plane:

```yaml
runtime:
  engine: native
nodes:
  filter:
    uses: native:/opt/nodrix/plugins/libfilter.so#demo.every_nth
```

The runner verifies the library, required symbols, exact ABI value, required
feature bits, function-table prefix, ports, types, and memory domains before
starting workers. `last_error()` is retained in run artifacts.

ABI 1.0 passed `nodrix::Node*` across the library boundary and is not loaded by
Nodrix 1.6 or later. Recompile plugins against `nodrix/c_api.h`.
