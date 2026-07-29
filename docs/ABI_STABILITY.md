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

## Buffers

`nodrix_buffer_v2` carries a byte span and optional `retain`/`release`
callbacks. If both callbacks are present, the host retains the buffer and
passes it through without copying. A buffer without ownership callbacks is
borrowed only for the current call; the host copies it if the plugin emits it.
Callbacks must be thread-safe and must not throw.

## Inspection

```bash
nodrix native inspect libplugin.so
```

External native plugins execute in the unified runtime:

```yaml
runtime:
  engine: unified
nodes:
  filter:
    uses: native:./libfilter.so#demo.every_nth
```

The old ABI 1.0 passed `nodrix::Node*` across the library boundary and is not
loaded by Nodrix 1.6 or later. Recompile plugins against `nodrix/c_api.h`.
