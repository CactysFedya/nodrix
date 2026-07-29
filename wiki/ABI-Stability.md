# ABI Stability

Plugin ABI 1.0 has numeric value `65536`. Inspect a library before loading:

```bash
nodrix native inspect libplugin.so
```

A different ABI is rejected before node creation.
