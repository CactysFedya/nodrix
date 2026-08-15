# Compatibility policy for the 2.x line

Plyctl is the public CLI and Python distribution. Nodrix remains the ecosystem,
repository, compatibility import, and historical on-disk identity.

## Preserved in 2.3.0b1

- `plyctl` command and package distribution.
- `nodrix` compatibility import and CLI alias.
- Manifest aliases accepted by the 2.x migration layer.
- Existing `.nodrix/` state and run directories.
- `.ndrx` recordings and native ABI names covered by the 2.x policy.
- Provider API 1 compatibility while Provider API 2 is preferred.

## Not guaranteed across platforms

Virtual environments, native wheels, build directories, and compiled plugins
are platform artifacts. A macOS artifact is not portable to Linux ARM64.
Transfer source plus locks, or use target-qualified wheels.

## Breaking changes

A breaking CLI, manifest, provider, ABI, wire, or artifact change requires:

1. an ADR;
2. a migration path;
3. a deprecation period where practical;
4. compatibility tests;
5. explicit release notes.
