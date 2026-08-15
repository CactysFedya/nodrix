"""Canonical identity primitives shared across Nodrix domains.

This module deliberately knows nothing about SystemModel, workflows, runtimes,
backends, datasets, or artifacts.  It provides stable references that those
domains can share without depending on each other.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ALGORITHM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _segment(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")

    if not _SEGMENT_RE.fullmatch(normalized):
        raise ValueError(
            f"{field} must start with an alphanumeric character and contain "
            "only letters, digits, '.', '_' or '-'"
        )

    return normalized


def _namespace(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("namespace must be a string")

    normalized = value.strip().strip("/")
    if not normalized:
        raise ValueError("namespace must be non-empty")

    parts = normalized.split("/")
    return "/".join(
        _segment(part, field="namespace segment")
        for part in parts
    )


@dataclass(frozen=True, slots=True)
class EntityRef:
    """Stable logical reference to one canonical Nodrix entity.

    EntityRef identifies the logical entity, not a particular revision of its
    definition and not a filesystem location.

    Example:

        nodrix://system/project/mapping
        nodrix://component/nodrix.mapping/voxel-map
    """

    kind: str
    namespace: str
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _segment(self.kind, field="kind").lower(),
        )
        object.__setattr__(
            self,
            "namespace",
            _namespace(self.namespace),
        )
        object.__setattr__(
            self,
            "name",
            _segment(self.name, field="name"),
        )

    @property
    def canonical(self) -> str:
        return f"nodrix://{self.kind}/{self.namespace}/{self.name}"

    def __str__(self) -> str:
        return self.canonical

    @classmethod
    def parse(cls, value: str) -> "EntityRef":
        if not isinstance(value, str):
            raise TypeError("entity reference must be a string")

        prefix = "nodrix://"
        if not value.startswith(prefix):
            raise ValueError(
                f"entity reference must start with {prefix!r}"
            )

        body = value[len(prefix):]
        parts = body.split("/")

        if len(parts) < 3:
            raise ValueError(
                "entity reference must contain kind, namespace and name"
            )

        kind = parts[0]
        namespace = "/".join(parts[1:-1])
        name = parts[-1]

        return cls(
            kind=kind,
            namespace=namespace,
            name=name,
        )


@dataclass(frozen=True, slots=True)
class RevisionRef:
    """Reference to one immutable revision of a logical entity."""

    entity: EntityRef
    algorithm: str
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.entity, EntityRef):
            raise TypeError("entity must be an EntityRef")

        if not isinstance(self.algorithm, str):
            raise TypeError("algorithm must be a string")

        algorithm = self.algorithm.strip().lower()
        if not algorithm or not _ALGORITHM_RE.fullmatch(algorithm):
            raise ValueError("invalid digest algorithm")

        if not isinstance(self.digest, str):
            raise TypeError("digest must be a string")

        digest = self.digest.strip().lower()
        if not digest:
            raise ValueError("digest must be non-empty")

        if algorithm == "sha256" and not _SHA256_RE.fullmatch(digest):
            raise ValueError(
                "sha256 digest must contain exactly 64 hexadecimal characters"
            )

        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "digest", digest)

    @property
    def canonical(self) -> str:
        return (
            f"{self.entity.canonical}"
            f"@{self.algorithm}:{self.digest}"
        )

    def __str__(self) -> str:
        return self.canonical

    @classmethod
    def from_sha256(
        cls,
        entity: EntityRef,
        digest: str,
    ) -> "RevisionRef":
        """Bridge existing raw SystemModel SHA-256 values into canonical refs."""

        return cls(
            entity=entity,
            algorithm="sha256",
            digest=digest,
        )

    @classmethod
    def parse(cls, value: str) -> "RevisionRef":
        if not isinstance(value, str):
            raise TypeError("revision reference must be a string")

        entity_text, separator, revision = value.rpartition("@")
        if not separator:
            raise ValueError(
                "revision reference must contain '@'"
            )

        algorithm, separator, digest = revision.partition(":")
        if not separator:
            raise ValueError(
                "revision reference must contain '<algorithm>:<digest>'"
            )

        return cls(
            entity=EntityRef.parse(entity_text),
            algorithm=algorithm,
            digest=digest,
        )


__all__ = [
    "EntityRef",
    "RevisionRef",
]
