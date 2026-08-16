# Canonical Storage Standard v1

The Canonical Storage Standard defines how Nodrix maps canonical objects,
execution history, materialized data, and managed state to local project
storage.

The governing rule is:

> Identity does not come from storage.

Canonical identity is defined by the canonical object model. Storage resolves
that identity to physical locations; filesystem paths never become the source
of EntityRef or RevisionRef identity.

## 1. Project storage classes

A Nodrix project may contain these top-level storage roots:

    project/
    ├── datasets/
    ├── artifacts/
    ├── outputs/
    └── .nodrix/

Their meanings are intentionally different.

`datasets/` is canonical local storage for materialized Dataset revisions.

`artifacts/` is canonical local storage for materialized Artifact revisions.

`outputs/` is legacy or explicitly user-managed compatibility storage. New
canonical materialization must not use it as its canonical root.

`.nodrix/` contains Nodrix-managed state, history, generated state, and caches.
It is not the canonical home for large Dataset or Artifact payloads.

## 2. Managed project layout

The canonical project-managed layout is provided by `StorageLayout`:

    .nodrix/
    ├── runs/
    ├── logs/
    ├── operations/
    ├── benchmarks/
    ├── optimization/
    ├── build/
    ├── prefix/
    ├── generated/
    ├── cache/
    │   └── workflows/
    ├── native-build/
    ├── system-generated/
    ├── context
    ├── shell.rc
    └── supervisor.json

The meanings are:

- `runs/` — durable Run history;
- `logs/` — managed runtime logs;
- `operations/` — engineering-operation history and evidence;
- `benchmarks/` — benchmark history and evidence;
- `optimization/` — optimization history and evidence;
- `build/` — Nodrix-managed build state;
- `prefix/` — managed installation prefixes;
- `generated/` — generated project/runtime state;
- `cache/` — disposable acceleration state;
- `native-build/` — compatibility native build state;
- `system-generated/` — generated compatibility System manifests;
- `context`, `shell.rc`, and `supervisor.json` — workspace/runtime state.

`StorageLayout` is path policy only. It does not create data, derive identity,
persist Runs, or own retention.

## 3. Global storage is separate

`$NODRIX_HOME`, with `~/.nodrix` as its default, is user/global Nodrix storage.

It is not `StorageLayout(project)` and must not be treated as project-managed
storage. Globally installed packages or other user-level resources may live
under this global root.

## 4. Materialized identity

DatasetRecord and ArtifactRecord follow the same identity law:

    EntityRef
        +
    RevisionRef
        +
    physical location

The physical location does not define EntityRef or RevisionRef.

Moving a physical representation does not change canonical identity. Changing
materialized content creates a new content revision.

## 5. Canonical local revision layout

One locally materialized revision is stored below either `datasets/` or
`artifacts/`:

    <root>/
    └── <entity-kind>/
        └── <readable-name>--<entity-key>/
            └── revisions/
                └── <revision-key>/
                    ├── payload
                    ├── materialization.json
                    └── lifecycle.json

`lifecycle.json` is optional and appears only when lifecycle state is explicitly
changed.

The readable name is convenience only. The entity key is derived from the full
canonical EntityRef so namespaces, case differences, and custom entity kinds
cannot silently collide on portable filesystems.

The revision directory is derived from RevisionRef.

## 6. Payload identity

For a regular file, revision identity is SHA-256 over the exact file bytes.

For a directory, Nodrix uses the versioned deterministic tree digest:

    nodrix.materialized-tree/v1

The tree digest includes deterministic relative paths, entry types, file sizes,
and file-content hashes. Modification timestamps are not content identity.

Symbolic links and special filesystem entries are rejected from canonical
materialized payloads.

## 7. Canonical payload name

The payload inside a canonical revision directory is always named:

    payload

The original source filename is not revision identity.

Therefore two source files with different names but identical bytes may resolve
to the same RevisionRef and the same canonical local materialization.

Human-readable aliases or snapshots may preserve domain-specific extensions
outside the canonical immutable revision directory.

## 8. Materialization descriptor

Each canonical local revision contains:

    materialization.json

Its schema is:

    nodrix.materialization/v1

The descriptor records intrinsic physical facts:

- Dataset or Artifact storage scope;
- EntityRef;
- RevisionRef;
- canonical local URI;
- payload type;
- payload size.

It deliberately does not record DatasetRecord or ArtifactRecord semantic fields
such as `kind`, `media_type`, or user metadata. Those belong to the canonical
model record rather than physical storage identity.

The descriptor records an already-existing canonical identity. It does not
create that identity.

## 9. Materialization

Canonical materialization performs these steps:

1. resolve the source payload;
2. compute deterministic content identity;
3. create the RevisionRef;
4. derive the canonical revision directory;
5. copy into a staging directory beside the target;
6. verify the staged payload;
7. install it atomically;
8. write the materialization descriptor;
9. return a DatasetRecord or ArtifactRecord.

An existing matching materialization is reused idempotently.

Existing storage whose content disagrees with its canonical revision is a
conflict and must not be silently overwritten.

## 10. Discovery

Exact lookup by RevisionRef is deterministic and does not require a database.

Entity-scoped revision discovery uses self-describing `materialization.json`
documents.

A future search index or database may accelerate discovery, but it must be
rebuildable from canonical storage descriptors and must never become identity
authority.

## 11. Lifecycle

Materialized retention state is separate from identity and intrinsic physical
facts.

Optional mutable lifecycle state is stored in:

    lifecycle.json

Its schema is:

    nodrix.materialized-lifecycle/v1

The lifecycle model contains:

    retention = retained | ephemeral
    pinned    = true | false

When no lifecycle document exists, the default is:

    retention = retained
    pinned    = false

Storage `pinned` means retention protection. It is distinct from an Operation
pinning `subject_revision` during planning.

Lifecycle changes never change EntityRef or RevisionRef.

## 12. Explicit deletion and pruning

Materialization, lookup, and listing never automatically remove old revisions.

Deletion is explicit. Pinned revisions cannot be removed until explicitly
unpinned.

Ephemeral pruning removes only revisions that satisfy both conditions:

    retention = ephemeral
    pinned    = false

Retained revisions and pinned ephemeral revisions survive pruning.

The storage API does not own the canonical `cleanup` Operation. Connecting
cleanup Operations to storage lifecycle actions belongs to the normal:

    Operation -> Plan -> Executor

architecture.

## 13. Run storage

Canonical Run history remains under:

    .nodrix/runs/<run-id>/

Runs reference Dataset and Artifact revisions.

Large materialized payloads are not embedded into Run directories merely
because a Run consumed or produced them.

Legacy Run lookup may still inspect historic project `runs/` paths when
required for compatibility.

## 14. Mutable aliases and snapshots

Paths such as:

    artifacts/maps/metric/latest.ply
    artifacts/maps/semantic/objects.sqlite
    artifacts/maps/semantic/objects.json

may continue to exist as domain-facing mutable outputs, snapshots, or aliases.

They are not canonical immutable Revision identity.

A system may expose `artifacts/maps/metric/latest.ply` for convenient
consumption while independently materializing immutable Artifact revisions
under the canonical revision layout.

Replacing the mutable path does not alter the identity of already materialized
historical revisions.

## 15. Legacy compatibility

Compatibility does not make a legacy path canonical.

The following may remain supported where existing behavior requires them:

- project `outputs/`;
- historic project `runs/`;
- nested per-Run `outputs/`;
- domain-facing mutable Artifact snapshots;
- existing `.nodrix/native-build` and `.nodrix/system-generated` locations.

New canonical code must resolve project storage through `StorageLayout` and the
materialized-storage API rather than constructing competing roots.

New project scaffolds create `datasets/` and `artifacts/` as the materialized
roots and do not scaffold a root `outputs/` directory.

## 16. SDK boundary

The materialized-storage API is infrastructure, not authoring syntax.

It may be imported explicitly with:

    from nodrix.materialized_storage import ...

It is not re-exported from `nodrix.sdk`.

The SDK remains an authoring frontend and does not own storage, execution, or
persistence.

## 17. Canonical rule summary

The storage rules reduce to:

    identity
        !=
    path

    EntityRef + RevisionRef
        ↓
    storage policy
        ↓
    canonical physical location

    materialization.json
        = intrinsic physical facts

    lifecycle.json
        = mutable retention policy

    index/database
        = optional acceleration only

    outputs/
        = compatibility only

    datasets/ + artifacts/
        = canonical materialized project roots
