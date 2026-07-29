# Migration from 1.x to 2.0

Preview a migration without writing:

```bash
nodrix migrate pipeline.yaml --to v2 --dry-run
```

Create a separate v2 file:

```bash
nodrix migrate pipeline.yaml --to v2
# writes pipeline.v2.yaml
```

Replace the source only when explicitly requested:

```bash
nodrix migrate pipeline.yaml --to v2 --in-place
# creates pipeline.yaml.v1.bak before an atomic replacement
```

The migrator validates the complete result before writing. It adds the required
v2 sections, changes `engine: auto` to the explicit `unified` engine, and maps
`restart`/`disable_branch` to `restart_node`/`isolate_branch`. Numbered backups
are used when an earlier backup already exists.

After migration:

```bash
nodrix validate pipeline.v2.yaml --production
nodrix inspect pipeline.v2.yaml --memory
nodrix run pipeline.v2.yaml --production
```

Production mode additionally requires health timeouts, rejects implicit copies,
relative model paths, unprotected LAN exports, unsigned required plugins, and
hardware policies that permit a software fallback.
