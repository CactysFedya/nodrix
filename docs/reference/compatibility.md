# Compatibility policy for 2.x

Plyctl was renamed from Nodrix without breaking existing 2.x projects.

## Prefer in new work

```text
Product: Plyctl
CLI: plyctl
Python facade: plyctl
Manifest API: plyctl.dev/v2
Provider schema: plyctl-provider/2
Provider entry points: plyctl.providers
```

## Still supported throughout 2.x

```text
CLI and Python package: nodrix
Manifest APIs: nodrix.dev/v1, nodrix.dev/v2
Provider schemas: nodrix-provider/1, nodrix-provider/2
Provider entry points: nodrix.providers
Workspace file: nodrix.yaml
Runtime state directory: .nodrix/
Compatibility fields such as requires_nodrix
```

## Migration rule

Do not perform mass renames merely for appearance. Move public examples and new manifests to Plyctl names, while preserving compatibility identifiers where they are part of the stable 2.x protocol or on-disk format.
