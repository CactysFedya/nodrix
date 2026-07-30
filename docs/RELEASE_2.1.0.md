# Nodrix 2.1.0

Nodrix 2.1.0 introduces Provider API 1 and one unified doctor while preserving
all stable 2.0 contracts: Manifest v2, Python Node API, Plugin C ABI 2,
existing Node ids, `nodrix.lock`, NDRX2, the native runner, pipelines, and CLI
commands.

## Provider API 1

- Public metadata, Node, probe, template, runtime, and feature-negotiation
  contracts.
- Distribution discovery through the `nodrix.providers` entry-point group.
- Required `nodrix-provider.json` metadata and optional detached
  `nodrix-provider.sig`.
- Metadata-only list/info operations with no provider import.
- Version, schema, feature, distribution, and entry-point consistency checks.
- Detached Ed25519 verification against a local trust store.
- Explicit production allowlist and safe POSIX trust-store permissions.
- Lazy import only after verification and only when a Node or probe is
  selected.
- Production pipeline provider verification before imports.
- Legacy adapters for current Core, Vision, Media, Recording, and ROS 2 ids.

## Unified diagnostics

The new top-level commands are:

```bash
nodrix provider list
nodrix provider info <id>
nodrix provider verify <id>
nodrix doctor
nodrix doctor --deep
nodrix doctor --json
nodrix doctor --provider ros2
```

Safe probes run by default. Device-acquiring probes require `--deep`, retain a
declared timeout/permissions contract, and report evidence through
`nodrix-doctor/1`.

## Compatibility

No 2.0 feature was removed or silently changed. Legacy doctor commands and
provider prefixes remain supported. Uninstalling an external provider leaves
Core operational; a pipeline using that provider then fails with an explicit
unknown-provider/Node diagnostic.
