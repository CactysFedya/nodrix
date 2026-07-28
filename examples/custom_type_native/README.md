# Python → C++ custom type

This example generates a fixed-layout type from one YAML schema, passes it from
Python into a C++ plugin, modifies it natively, and decodes it back into the same
Python class.

```bash
nodrix type build telemetry.yaml -o generated
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
nodrix run pipeline.yaml
```

On macOS change the plugin path in `pipeline.yaml` from `.so` to `.dylib`.
