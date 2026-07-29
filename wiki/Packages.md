# Packages

```bash
nodrix init my-nodes --template package
nodrix package build .
nodrix package install dist/my-nodes-1.0.0.ndpkg
```

Use installed nodes as `my-nodes/node-name`. Nodrix verifies path safety and SHA-256 checksums.
