"""Canonical materialized data and artifact records.

DatasetRecord and ArtifactRecord represent materialized, addressable revisions
of logical Nodrix entities.

Logical identity is carried by EntityRef.  Immutable content identity is
carried by RevisionRef.  Physical or remote location is carried separately by
``uri`` and therefore never defines canonical identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Mapping

from .identity import EntityRef, RevisionRef


_KIND_RE = re.compile(r"^[a-z][a-z0-9._-]*$")


def _kind(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")

    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")

    if not _KIND_RE.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must start with a letter and contain only "
            "lowercase letters, digits, '.', '_' or '-'"
        )

    return normalized


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")

    return normalized


def _optional_text(
    value: str | None,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    return _required_text(
        value,
        field_name=field_name,
    )


def _size_bytes(value: int | None) -> int | None:
    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("size_bytes must be an integer or None")

    if value < 0:
        raise ValueError("size_bytes cannot be negative")

    return value


def _validate_identity(
    entity: EntityRef,
    revision: RevisionRef,
) -> None:
    if not isinstance(entity, EntityRef):
        raise TypeError("entity must be an EntityRef")

    if not isinstance(revision, RevisionRef):
        raise TypeError("revision must be a RevisionRef")

    if revision.entity != entity:
        raise ValueError(
            "revision must reference the record entity"
        )


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    """One materialized immutable revision of a logical dataset.

    ``kind`` is intentionally extensible.  Examples may include ``recording``,
    ``image-set``, ``point-cloud``, or user-defined namespaced kinds.

    ``uri`` describes where this materialization can currently be found.  It is
    not part of the dataset identity.
    """

    entity: EntityRef
    revision: RevisionRef
    kind: str
    uri: str
    media_type: str | None = None
    size_bytes: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identity(
            self.entity,
            self.revision,
        )

        object.__setattr__(
            self,
            "kind",
            _kind(
                self.kind,
                field_name="dataset kind",
            ),
        )

        object.__setattr__(
            self,
            "uri",
            _required_text(
                self.uri,
                field_name="dataset uri",
            ),
        )

        object.__setattr__(
            self,
            "media_type",
            _optional_text(
                self.media_type,
                field_name="dataset media_type",
            ),
        )

        object.__setattr__(
            self,
            "size_bytes",
            _size_bytes(self.size_bytes),
        )

        if not isinstance(self.metadata, Mapping):
            raise TypeError("dataset metadata must be a mapping")

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """One materialized immutable revision of a logical artifact.

    ArtifactRecord represents an actual produced result, unlike the existing
    SystemModel Artifact declaration which describes an output expected from a
    System.

    ``kind`` is extensible and may describe binaries, maps, reports, models,
    packages, container images, or user-defined artifact categories.
    """

    entity: EntityRef
    revision: RevisionRef
    kind: str
    uri: str
    media_type: str | None = None
    size_bytes: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identity(
            self.entity,
            self.revision,
        )

        object.__setattr__(
            self,
            "kind",
            _kind(
                self.kind,
                field_name="artifact kind",
            ),
        )

        object.__setattr__(
            self,
            "uri",
            _required_text(
                self.uri,
                field_name="artifact uri",
            ),
        )

        object.__setattr__(
            self,
            "media_type",
            _optional_text(
                self.media_type,
                field_name="artifact media_type",
            ),
        )

        object.__setattr__(
            self,
            "size_bytes",
            _size_bytes(self.size_bytes),
        )

        if not isinstance(self.metadata, Mapping):
            raise TypeError("artifact metadata must be a mapping")

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


__all__ = [
    "ArtifactRecord",
    "DatasetRecord",
]
