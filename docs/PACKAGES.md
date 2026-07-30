# Nodrix Packages

A package contains `nodrix.package.yaml`, Python/native nodes, type schemas, models, configs, tests and documentation.

```yaml
format: nodrix-package/1
name: cobra-perception
version: 1.0.0
nodrix: ">=2.0,<3.0"
abi: 2
platforms: [linux-x86_64, linux-aarch64]
hardware: []
sandbox: process
nodes:
  detector:
    python: python/detector.py:Detector
  tracker:
    native: native/libtracker.so#cobra.tracker
```

```bash
nodrix package build . --sign-key publisher-private.pem
nodrix plugin verify dist/cobra-perception-1.0.0.ndpkg \
  --public-key publisher-public.pem --require-signature
nodrix plugin install dist/cobra-perception-1.0.0.ndpkg \
  --public-key publisher-public.pem --require-signature
nodrix plugin search cobra
nodrix plugin info cobra-perception
nodrix plugin remove cobra-perception
```

Verification and extraction use the same open archive. Installation rejects
path traversal, absolute/Windows-unsafe names, symlinks, directory entries,
duplicates, cross-platform case/Unicode collisions, untracked members,
checksum mismatches, excessive file count, per-file/total size, and compression
ratio before extraction. Metadata name/version must match the packaged
manifest.

Extraction occurs in a private staging directory beside the target and is
committed with one atomic rename. Installed `name/version` directories are
immutable; reinstalling the same version fails instead of overwriting files.
The `current` pointer is replaced atomically. A failed verification or
compatibility check leaves no installed version.

Ed25519 verification binds the archive metadata and complete checksum set to a
trusted publisher key. The registry remains offline and does not download or
execute packages during search.
