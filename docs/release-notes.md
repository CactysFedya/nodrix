# Release notes

## Plyctl 2.2.0 alpha.5

This is the only release described in the public documentation. Older release
history remains in `CHANGELOG.md` and GitHub Releases.

### Highlights

- canonical `plyctl` CLI and Python SDK with compatible `nodrix` aliases;
- one Manifest v2 graph for Python, C++, ROS 2, processes, devices, and transports;
- independently installable Spatial, Mapping, ROS 2, and Spatial ROS 2 packages;
- Provider API 1 with signed metadata, compatibility checks, and lazy imports;
- native NCNN detector through Plugin C ABI 2;
- bilingual English and Russian documentation published by GitHub Pages.

### Compatibility

Existing `nodrix.dev/v1` and `nodrix.dev/v2` manifests remain readable in 2.x.
Use `plyctl migrate` when you want to rewrite a manifest to canonical Plyctl
names rather than because an immediate migration is required.

### Translation status

The Russian site covers the primary workflow and navigation. Deep API reference
pages continue to use the English source until their translations are added.
