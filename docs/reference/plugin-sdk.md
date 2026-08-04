# Native and plugin SDK reference

Use native plugins only for measured hot paths or when integrating an existing native library. Python nodes remain the fastest development path.

## C/C++ ABI

The 2.x native layer exposes versioned C symbols and a C++ wrapper. A plugin should:

- report the expected ABI version;
- declare feature bits such as typed ports, memory domains, and zero-copy buffers;
- reject unsupported host ABI versions;
- export node factories through the documented v2 symbols;
- compile with hidden visibility and release optimization.

Generated projects include an optional C++20 passthrough example under `native/`.

## Build pattern

```bash
cmake -S native -B native/build -DCMAKE_BUILD_TYPE=Release
cmake --build native/build --parallel
```

The generated CMake project asks Python for the installed `nodrix/native` include directory because the compatibility package still owns the native ABI headers in 2.x.

## Distribution

The plugin SDK supports packaged artifacts and verification workflows. Keep ABI metadata, platform tags, signatures, and dependencies explicit. Do not load a plugin compiled for another ABI or architecture.

## Isolation decision

Use in-process loading only for trusted, tested plugins. Prefer a managed external application or process-isolated plugin when a crash must not terminate the runtime.
