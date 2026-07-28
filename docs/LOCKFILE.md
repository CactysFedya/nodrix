# Reproducible lock file

```bash
nodrix lock pipeline.yaml
nodrix lock pipeline.yaml --check
nodrix run pipeline.yaml --locked
```

`nodrix.lock` records the runtime version, Python/platform metadata, dependency versions, and SHA-256/size for the manifest, local node code, native libraries, models, configs, type schemas and installed package contents. A changed, missing or newly introduced locked input fails `--locked` execution.
