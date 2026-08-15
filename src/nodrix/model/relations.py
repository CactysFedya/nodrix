"""Canonical typed relations and provenance graph.

Relations connect logical entities, immutable revisions, and historical records
without forcing all of those concepts into one inheritance hierarchy.

The relation vocabulary is extensible.  Nodrix provides a small canonical set,
while domains and packages may introduce namespaced relation kinds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Mapping

from .identity import EntityRef, RevisionRef
from .references import CanonicalRef, RecordRef


_RELATION_KIND_RE = re.compile(r"^[a-z][a-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class RelationKind:
    """Stable extensible relation predicate."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("relation kind must be a string")

        normalized = self.value.strip().lower()
        if not normalized:
            raise ValueError("relation kind must be non-empty")

        if not _RELATION_KIND_RE.fullmatch(normalized):
            raise ValueError(
                "relation kind must start with a letter and contain only "
                "lowercase letters, digits, '.', '_' or '-'"
            )

        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(
        cls,
        value: str | "RelationKind",
    ) -> "RelationKind":
        if isinstance(value, cls):
            return value
        return cls(value)


CONSUMES = RelationKind("consumes")
PRODUCES = RelationKind("produces")
DERIVED_FROM = RelationKind("derived_from")
SUPERSEDES = RelationKind("supersedes")

EXECUTED_AS = RelationKind("executed_as")
RECORDED_AS = RelationKind("recorded_as")

REQUIRES = RelationKind("requires")
PROVIDES = RelationKind("provides")
DEPENDS_ON = RelationKind("depends_on")
PLACED_ON = RelationKind("placed_on")


def _endpoint(
    value: CanonicalRef,
    *,
    field_name: str,
) -> CanonicalRef:
    if not isinstance(
        value,
        (EntityRef, RevisionRef, RecordRef),
    ):
        raise TypeError(
            f"{field_name} must be an EntityRef, RevisionRef or RecordRef"
        )

    return value


@dataclass(frozen=True, slots=True)
class Relation:
    """One typed directed edge in the canonical object graph."""

    source: CanonicalRef
    kind: RelationKind | str
    target: CanonicalRef
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source",
            _endpoint(
                self.source,
                field_name="relation source",
            ),
        )

        object.__setattr__(
            self,
            "kind",
            RelationKind.parse(self.kind),
        )

        object.__setattr__(
            self,
            "target",
            _endpoint(
                self.target,
                field_name="relation target",
            ),
        )

        if not isinstance(self.metadata, Mapping):
            raise TypeError("relation metadata must be a mapping")

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

    @property
    def kind_name(self) -> str:
        return str(self.kind)


@dataclass(frozen=True, slots=True)
class RelationGraph:
    """Immutable collection of canonical relations.

    This is intentionally a small graph abstraction rather than a graph
    database.  Persistence, indexing, and storage backends belong to later
    layers.
    """

    relations: tuple[Relation, ...] = ()

    def __post_init__(self) -> None:
        try:
            relations = tuple(self.relations)
        except TypeError as exc:
            raise TypeError(
                "relations must be an iterable of Relation objects"
            ) from exc

        for relation in relations:
            if not isinstance(relation, Relation):
                raise TypeError(
                    "relations must contain only Relation objects"
                )

        object.__setattr__(
            self,
            "relations",
            relations,
        )

    def outgoing(
        self,
        source: CanonicalRef,
        *,
        kind: RelationKind | str | None = None,
    ) -> tuple[Relation, ...]:
        source = _endpoint(
            source,
            field_name="source",
        )

        relation_kind = (
            None
            if kind is None
            else RelationKind.parse(kind)
        )

        return tuple(
            relation
            for relation in self.relations
            if relation.source == source
            and (
                relation_kind is None
                or relation.kind == relation_kind
            )
        )

    def incoming(
        self,
        target: CanonicalRef,
        *,
        kind: RelationKind | str | None = None,
    ) -> tuple[Relation, ...]:
        target = _endpoint(
            target,
            field_name="target",
        )

        relation_kind = (
            None
            if kind is None
            else RelationKind.parse(kind)
        )

        return tuple(
            relation
            for relation in self.relations
            if relation.target == target
            and (
                relation_kind is None
                or relation.kind == relation_kind
            )
        )


__all__ = [
    "CONSUMES",
    "DEPENDS_ON",
    "DERIVED_FROM",
    "EXECUTED_AS",
    "PLACED_ON",
    "PRODUCES",
    "PROVIDES",
    "RECORDED_AS",
    "REQUIRES",
    "SUPERSEDES",
    "Relation",
    "RelationGraph",
    "RelationKind",
]
