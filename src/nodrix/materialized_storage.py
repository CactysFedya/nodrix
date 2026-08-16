"""Canonical local paths for materialized Dataset and Artifact revisions.

This module bridges canonical immutable identity to the project storage layout.

It deliberately does not:

- create directories;
- write, copy or move payloads;
- choose payload filenames;
- mutate DatasetRecord or ArtifactRecord;
- treat a filesystem path as canonical identity.

Storage path derivation is deterministic from RevisionRef, while the canonical
identity remains the RevisionRef itself.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .model import RevisionRef
from .storage_layout import StorageLayout


_ENTITY_PREFIX_LIMIT = 48


def _require_revision(
    revision: RevisionRef,
) -> RevisionRef:
    if not isinstance(
        revision,
        RevisionRef,
    ):
        raise TypeError(
            "revision must be a RevisionRef"
        )

    return revision


def _entity_storage_key(
    revision: RevisionRef,
) -> str:
    entity = revision.entity

    digest = hashlib.sha256(
        entity.canonical.encode(
            "utf-8"
        )
    ).hexdigest()

    # The readable prefix is convenience only. The complete canonical EntityRef
    # hash is what prevents collisions between namespaces, names that differ
    # only by case, and other identities that map poorly to portable paths.
    prefix = (
        entity.name
        .lower()[
            :_ENTITY_PREFIX_LIMIT
        ]
    )

    return (
        f"{prefix}--{digest}"
    )


def _revision_storage_key(
    revision: RevisionRef,
) -> str:
    # SHA-256 is already validated as exactly 64 hexadecimal characters by the
    # canonical identity model, so preserve it directly for inspectability.
    if revision.algorithm == "sha256":
        return (
            f"sha256-{revision.digest}"
        )

    # Custom RevisionRef algorithms intentionally permit opaque digest strings.
    # Hash the textual digest before using it as a path component so arbitrary
    # custom digests can never introduce separators, traversal or filesystem
    # portability problems.
    digest_key = hashlib.sha256(
        revision.digest.encode(
            "utf-8"
        )
    ).hexdigest()

    return (
        f"{revision.algorithm}"
        f"-key-{digest_key}"
    )


def _revision_directory(
    root: Path,
    revision: RevisionRef,
) -> Path:
    resolved = _require_revision(
        revision
    )

    return (
        root
        / resolved.entity.kind
        / _entity_storage_key(
            resolved
        )
        / "revisions"
        / _revision_storage_key(
            resolved
        )
    )


def dataset_revision_directory(
    project: str | Path,
    revision: RevisionRef,
) -> Path:
    """Return canonical local storage for one Dataset revision."""

    return _revision_directory(
        StorageLayout(
            project
        ).datasets_root,
        revision,
    )


def artifact_revision_directory(
    project: str | Path,
    revision: RevisionRef,
) -> Path:
    """Return canonical local storage for one Artifact revision."""

    return _revision_directory(
        StorageLayout(
            project
        ).artifacts_root,
        revision,
    )


__all__ = [
    "artifact_revision_directory",
    "dataset_revision_directory",
]
