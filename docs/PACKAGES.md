# Nodrix Packages

A package contains `nodrix.package.yaml`, Python/native nodes, type schemas, models, configs, tests and documentation.

```yaml
format: nodrix-package/1
name: cobra-perception
version: 1.0.0
nodrix: ">=1.0,<2.0"
nodes:
  detector:
    python: python/detector.py:Detector
  tracker:
    native: native/libtracker.so#cobra.tracker
```

```bash
nodrix package build .
nodrix package install dist/cobra-perception-1.0.0.ndpkg
nodrix package list
nodrix package info cobra-perception
nodrix package remove cobra-perception
```

Installation rejects path traversal and checksum mismatches. Nodrix 1.0 does not download or execute packages from a remote marketplace.
