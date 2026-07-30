# Plugin SDK and Registry

Nodrix supports Python nodes, native Plugin C ABI 2 nodes, and offline `.ndpkg`
packages. The native ABI contract is documented in `ABI_STABILITY.md`.

A package manifest declares compatibility and capabilities:

```yaml
format: nodrix-package/1
name: perception-pack
version: 2.1.0
nodrix: ">=2.0,<3.0"
abi: 2
platforms: [linux-x86_64, linux-aarch64]
hardware: [cuda]
sandbox: process
nodes:
  detector:
    native: native/libdetector.so#perception.detector
```

Build and sign with an Ed25519 private key:

```bash
nodrix package build . --sign-key publisher-private.pem
nodrix plugin verify dist/perception-pack-2.1.0.ndpkg \
  --public-key publisher-public.pem --require-signature
nodrix plugin install dist/perception-pack-2.1.0.ndpkg \
  --public-key publisher-public.pem --require-signature
```

Other offline registry commands are `plugin search`, `plugin info`, and
`plugin remove`. Installation verifies safe portable paths, resource limits,
the complete member set, and every SHA-256 checksum before extraction.
Versions are immutable and atomically installed. A trusted public key is
required to mark the signature as verified; the verification record is
retained with the installation.

Native plugins are trusted machine code. Use process isolation when the
publisher or implementation is outside the deployment trust boundary. In
production, direct `native:/absolute/library#type` references must reside below
an absolute `security.native_plugin_allowlist` entry and world-writable
libraries are rejected. Signed installed packages are the preferred deployment
unit.
