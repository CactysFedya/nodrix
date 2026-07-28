# Plugin ABI 1.0

The official ABI value is `0x00010000` (`65536`). `NODRIX_DECLARE_PLUGIN` exports:

```text
nodrix_plugin_abi_version
nodrix_plugin_features
nodrix_create_node
nodrix_destroy_node
```

Feature bit 0 is typed ports. Feature bit 1 is memory-domain port contracts.

```bash
nodrix native inspect libplugin.so
```

The loader rejects a different ABI before node creation. Plugins built against experimental 0.9 ABI 3 must be recompiled.
