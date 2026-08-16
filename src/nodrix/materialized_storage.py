"""Canonical local storage for materialized Dataset and Artifact revisions.

This module bridges immutable canonical identity to local project storage.

The canonical identity remains EntityRef + RevisionRef. Filesystem paths are
only physical locations derived from that identity.

Materialization rules:

- regular files use SHA-256 of their exact bytes;
- directories use a deterministic SHA-256 tree digest;
- directory digest includes relative paths, entry types, file sizes and file
  content hashes;
- timestamps and platform-specific file metadata are not content identity;
- symbolic links and special files are rejected;
- canonical revision directories are immutable;
- materialization is staged next to the final revision and atomically renamed;
- the canonical payload name is always ``payload``.

The module does not own Run persistence, provenance or SDK authoring.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, Mapping

from .model import (
    ArtifactRecord,
    DatasetRecord,
    EntityRef,
    RevisionRef,
)
from .storage_layout import StorageLayout


_ENTITY_PREFIX_LIMIT = 48
_TREE_DIGEST_SCHEMA = b"nodrix.materialized-tree/v1\n"
_PAYLOAD_NAME = "payload"


class MaterializationError(RuntimeError):
    """Base error for canonical local materialization."""


class MaterializationConflictError(MaterializationError):
    """Existing immutable storage disagrees with its canonical revision."""


@dataclass(frozen=True, slots=True)
class _PayloadInfo:
    payload_type: str
    digest: str
    size_bytes: int


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


def _require_entity(
    entity: EntityRef,
) -> EntityRef:
    if not isinstance(
        entity,
        EntityRef,
    ):
        raise TypeError(
            "entity must be an EntityRef"
        )

    return entity


def _entity_storage_key(
    revision: RevisionRef,
) -> str:
    entity = revision.entity

    digest = hashlib.sha256(
        entity.canonical.encode(
            "utf-8"
        )
    ).hexdigest()

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
    if revision.algorithm == "sha256":
        return (
            f"sha256-{revision.digest}"
        )

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


def _file_info(
    path: Path,
) -> _PayloadInfo:
    digest = hashlib.sha256()
    size = 0

    with path.open(
        "rb"
    ) as stream:
        for chunk in iter(
            lambda: stream.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(
                chunk
            )
            size += len(
                chunk
            )

    return _PayloadInfo(
        payload_type="file",
        digest=digest.hexdigest(),
        size_bytes=size,
    )


def _tree_entry(
    digest: Any,
    document: Mapping[str, Any],
) -> None:
    encoded = json.dumps(
        dict(document),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode(
        "utf-8"
    )

    digest.update(
        encoded
    )
    digest.update(
        b"\n"
    )


def _tree_info(
    root: Path,
) -> _PayloadInfo:
    digest = hashlib.sha256()
    digest.update(
        _TREE_DIGEST_SCHEMA
    )

    total_size = 0

    def visit(
        directory: Path,
        parts: tuple[str, ...],
    ) -> None:
        nonlocal total_size

        entries = sorted(
            directory.iterdir(),
            key=lambda item: item.name,
        )

        for child in entries:
            relative_parts = (
                *parts,
                child.name,
            )

            relative = "/".join(
                relative_parts
            )

            info = child.lstat()
            mode = info.st_mode

            if stat.S_ISLNK(
                mode
            ):
                raise MaterializationError(
                    "materialized directories cannot "
                    f"contain symbolic links: {relative}"
                )

            if stat.S_ISDIR(
                mode
            ):
                _tree_entry(
                    digest,
                    {
                        "path": relative,
                        "type": "directory",
                    },
                )

                visit(
                    child,
                    relative_parts,
                )

                continue

            if stat.S_ISREG(
                mode
            ):
                file_info = _file_info(
                    child
                )

                total_size += (
                    file_info.size_bytes
                )

                _tree_entry(
                    digest,
                    {
                        "path": relative,
                        "sha256": (
                            file_info.digest
                        ),
                        "size_bytes": (
                            file_info.size_bytes
                        ),
                        "type": "file",
                    },
                )

                continue

            raise MaterializationError(
                "materialized directories can contain "
                "only regular files and directories: "
                f"{relative}"
            )

    visit(
        root,
        (),
    )

    return _PayloadInfo(
        payload_type="directory",
        digest=digest.hexdigest(),
        size_bytes=total_size,
    )


def _payload_info(
    path: Path,
) -> _PayloadInfo:
    if path.is_symlink():
        raise MaterializationError(
            "materialized payload cannot be a symbolic link"
        )

    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise

    if stat.S_ISREG(
        mode
    ):
        return _file_info(
            path
        )

    if stat.S_ISDIR(
        mode
    ):
        return _tree_info(
            path
        )

    raise MaterializationError(
        "materialized payload must be a regular file or directory"
    )


def _resolve_source(
    layout: StorageLayout,
    source: str | Path,
) -> Path:
    selected = Path(
        source
    ).expanduser()

    if not selected.is_absolute():
        selected = (
            layout.project_root
            / selected
        )

    if selected.is_symlink():
        raise MaterializationError(
            "materialization source cannot be a symbolic link"
        )

    return selected.resolve(
        strict=True
    )


def _payload_uri(
    layout: StorageLayout,
    payload: Path,
) -> str:
    return payload.relative_to(
        layout.project_root
    ).as_posix()


def _matches_payload(
    payload: Path,
    expected: _PayloadInfo,
) -> bool:
    try:
        actual = _payload_info(
            payload
        )
    except (
        FileNotFoundError,
        OSError,
        MaterializationError,
    ):
        return False

    return actual == expected


def _require_existing_payload(
    revision_directory: Path,
    payload: Path,
    expected: _PayloadInfo,
) -> None:
    if revision_directory.is_symlink():
        raise MaterializationConflictError(
            "canonical revision directory cannot be a symbolic link: "
            f"{revision_directory}"
        )

    if not _matches_payload(
        payload,
        expected,
    ):
        raise MaterializationConflictError(
            "existing canonical revision storage does not match "
            f"its expected immutable content: {revision_directory}"
        )


def _copy_payload(
    source: Path,
    destination: Path,
    payload_type: str,
) -> None:
    if payload_type == "file":
        shutil.copyfile(
            source,
            destination,
        )
        return

    shutil.copytree(
        source,
        destination,
        symlinks=True,
    )


def _build_record(
    *,
    dataset: bool,
    layout: StorageLayout,
    entity: EntityRef,
    revision: RevisionRef,
    kind: str,
    payload: Path,
    media_type: str | None,
    size_bytes: int,
    metadata: Mapping[str, Any] | None,
) -> DatasetRecord | ArtifactRecord:
    values = {
        "entity": entity,
        "revision": revision,
        "kind": kind,
        "uri": _payload_uri(
            layout,
            payload,
        ),
        "media_type": media_type,
        "size_bytes": size_bytes,
        "metadata": (
            {}
            if metadata is None
            else metadata
        ),
    }

    if dataset:
        return DatasetRecord(
            **values,
        )

    return ArtifactRecord(
        **values,
    )


def _materialize(
    *,
    project: str | Path,
    source: str | Path,
    entity: EntityRef,
    kind: str,
    dataset: bool,
    media_type: str | None,
    metadata: Mapping[str, Any] | None,
) -> DatasetRecord | ArtifactRecord:
    resolved_entity = _require_entity(
        entity
    )

    layout = StorageLayout(
        project
    )

    source_path = _resolve_source(
        layout,
        source,
    )

    source_info = _payload_info(
        source_path
    )

    revision = RevisionRef.from_sha256(
        resolved_entity,
        source_info.digest,
    )

    revision_directory = (
        dataset_revision_directory(
            layout.project_root,
            revision,
        )
        if dataset
        else artifact_revision_directory(
            layout.project_root,
            revision,
        )
    )

    payload = (
        revision_directory
        / _PAYLOAD_NAME
    )

    if (
        source_info.payload_type
        == "directory"
        and revision_directory.is_relative_to(
            source_path
        )
    ):
        raise MaterializationError(
            "cannot materialize a directory into storage "
            "contained by that same source directory"
        )

    if (
        revision_directory.exists()
        or revision_directory.is_symlink()
    ):
        _require_existing_payload(
            revision_directory,
            payload,
            source_info,
        )

        return _build_record(
            dataset=dataset,
            layout=layout,
            entity=resolved_entity,
            revision=revision,
            kind=kind,
            payload=payload,
            media_type=media_type,
            size_bytes=source_info.size_bytes,
            metadata=metadata,
        )

    revision_directory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    staging = Path(
        tempfile.mkdtemp(
            prefix=(
                f".{revision_directory.name}"
                ".materialize-"
            ),
            dir=revision_directory.parent,
        )
    )

    try:
        staged_payload = (
            staging
            / _PAYLOAD_NAME
        )

        _copy_payload(
            source_path,
            staged_payload,
            source_info.payload_type,
        )

        staged_info = _payload_info(
            staged_payload
        )

        if staged_info != source_info:
            raise MaterializationError(
                "materialization source changed while it was being copied"
            )

        try:
            os.replace(
                staging,
                revision_directory,
            )
        except OSError as exc:
            if (
                revision_directory.exists()
                and not revision_directory.is_symlink()
                and _matches_payload(
                    payload,
                    source_info,
                )
            ):
                pass
            else:
                raise MaterializationConflictError(
                    "canonical revision storage appeared concurrently "
                    "with different content: "
                    f"{revision_directory}"
                ) from exc

    finally:
        if staging.exists():
            shutil.rmtree(
                staging,
                ignore_errors=True,
            )

    _require_existing_payload(
        revision_directory,
        payload,
        source_info,
    )

    return _build_record(
        dataset=dataset,
        layout=layout,
        entity=resolved_entity,
        revision=revision,
        kind=kind,
        payload=payload,
        media_type=media_type,
        size_bytes=source_info.size_bytes,
        metadata=metadata,
    )


def materialize_dataset(
    *,
    project: str | Path = ".",
    source: str | Path,
    entity: EntityRef,
    kind: str,
    media_type: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DatasetRecord:
    """Materialize one immutable Dataset revision into canonical local storage."""

    record = _materialize(
        project=project,
        source=source,
        entity=entity,
        kind=kind,
        dataset=True,
        media_type=media_type,
        metadata=metadata,
    )

    assert isinstance(
        record,
        DatasetRecord,
    )

    return record


def materialize_artifact(
    *,
    project: str | Path = ".",
    source: str | Path,
    entity: EntityRef,
    kind: str,
    media_type: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ArtifactRecord:
    """Materialize one immutable Artifact revision into canonical local storage."""

    record = _materialize(
        project=project,
        source=source,
        entity=entity,
        kind=kind,
        dataset=False,
        media_type=media_type,
        metadata=metadata,
    )

    assert isinstance(
        record,
        ArtifactRecord,
    )

    return record


def verify_materialized_record(
    project: str | Path,
    record: DatasetRecord | ArtifactRecord,
) -> bool:
    """Verify one canonical local materialized record against stored content."""

    if not isinstance(
        record,
        (
            DatasetRecord,
            ArtifactRecord,
        ),
    ):
        raise TypeError(
            "record must be a DatasetRecord or ArtifactRecord"
        )

    if record.revision.algorithm != "sha256":
        return False

    layout = StorageLayout(
        project
    )

    revision_directory = (
        dataset_revision_directory(
            layout.project_root,
            record.revision,
        )
        if isinstance(
            record,
            DatasetRecord,
        )
        else artifact_revision_directory(
            layout.project_root,
            record.revision,
        )
    )

    payload = (
        revision_directory
        / _PAYLOAD_NAME
    )

    if record.uri != _payload_uri(
        layout,
        payload,
    ):
        return False

    try:
        info = _payload_info(
            payload
        )
    except (
        FileNotFoundError,
        OSError,
        MaterializationError,
    ):
        return False

    if info.digest != record.revision.digest:
        return False

    if (
        record.size_bytes is not None
        and info.size_bytes
        != record.size_bytes
    ):
        return False

    return True


__all__ = [
    "MaterializationConflictError",
    "MaterializationError",
    "artifact_revision_directory",
    "dataset_revision_directory",
    "materialize_artifact",
    "materialize_dataset",
    "verify_materialized_record",
]
