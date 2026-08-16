"""Canonical provenance helpers for materialized data and Run I/O.

A Run consumes and produces immutable revisions, not filesystem paths and not
mutable logical entity names.

DatasetRecord and ArtifactRecord are convenient materialized records, while a
raw RevisionRef allows future user-defined record types to participate without
changing the canonical provenance model.

Materialized lineage also connects immutable revisions directly:

    derived --derived_from--> source
    newer   --supersedes----> older

``superseded_by`` is intentionally represented as an inverse query over
``SUPERSEDES`` rather than as a second persisted relation kind.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeAlias

from .data import ArtifactRecord, DatasetRecord
from .identity import RevisionRef
from .references import RecordRef
from .relations import (
    CONSUMES,
    DERIVED_FROM,
    PRODUCES,
    SUPERSEDES,
    Relation,
    RelationGraph,
)
from .runs import RunRecord


MaterializedRef: TypeAlias = (
    RevisionRef
    | DatasetRecord
    | ArtifactRecord
)


def materialized_revision(
    value: MaterializedRef,
) -> RevisionRef:
    """Return the canonical immutable revision of one materialized value."""

    if isinstance(
        value,
        RevisionRef,
    ):
        return value

    if isinstance(
        value,
        (
            DatasetRecord,
            ArtifactRecord,
        ),
    ):
        return value.revision

    raise TypeError(
        "provenance item must be a RevisionRef, "
        "DatasetRecord or ArtifactRecord"
    )


def _unique_revisions(
    values: Iterable[MaterializedRef],
) -> tuple[RevisionRef, ...]:
    if isinstance(
        values,
        (
            str,
            bytes,
        ),
    ):
        raise TypeError(
            "provenance items must be an iterable "
            "of materialized records or revisions"
        )

    try:
        iterator = iter(values)
    except TypeError as exc:
        raise TypeError(
            "provenance items must be iterable"
        ) from exc

    result: list[RevisionRef] = []
    seen: set[RevisionRef] = set()

    for value in iterator:
        revision = materialized_revision(
            value
        )

        if revision in seen:
            continue

        seen.add(
            revision
        )

        result.append(
            revision
        )

    return tuple(
        result
    )


def run_ref(
    run: RunRecord,
) -> RecordRef:
    """Return the canonical historical reference of one Run."""

    if not isinstance(
        run,
        RunRecord,
    ):
        raise TypeError(
            "run must be a RunRecord"
        )

    return RecordRef(
        kind="run",
        record_id=run.run_id,
    )


def run_io_relations(
    run: RunRecord,
    *,
    inputs: Iterable[MaterializedRef] = (),
    outputs: Iterable[MaterializedRef] = (),
) -> RelationGraph:
    """Build canonical Run input/output provenance relations.

    Inputs are projected as::

        Run --consumes--> Revision

    Outputs are projected as::

        Run --produces--> Revision

    Relations point to immutable revisions so provenance remains stable even if
    logical names are reused or physical locations change.
    """

    canonical_run = run_ref(
        run
    )

    consumed = _unique_revisions(
        inputs
    )

    produced = _unique_revisions(
        outputs
    )

    relations = tuple(
        Relation(
            source=canonical_run,
            kind=CONSUMES,
            target=revision,
        )
        for revision in consumed
    ) + tuple(
        Relation(
            source=canonical_run,
            kind=PRODUCES,
            target=revision,
        )
        for revision in produced
    )

    return RelationGraph(
        relations=relations,
    )


def materialized_lineage_relations(
    subject: MaterializedRef,
    *,
    derived_from: Iterable[
        MaterializedRef
    ] = (),
    supersedes: Iterable[
        MaterializedRef
    ] = (),
) -> RelationGraph:
    """Build canonical lineage for one materialized revision.

    ``derived_from`` may reference revisions of any logical entity.

    ``supersedes`` represents revision succession and therefore must reference
    older revisions of the same logical entity as ``subject``.

    The canonical direction is always::

        subject --derived_from--> source
        subject --supersedes----> previous

    No redundant ``superseded_by`` edge is stored.  It is derived by querying
    incoming ``SUPERSEDES`` relations.
    """

    revision = materialized_revision(
        subject
    )

    sources = _unique_revisions(
        derived_from
    )

    previous = _unique_revisions(
        supersedes
    )

    for source in sources:
        if source == revision:
            raise ValueError(
                "a revision cannot be derived from itself"
            )

    for older in previous:
        if older == revision:
            raise ValueError(
                "a revision cannot supersede itself"
            )

        if older.entity != revision.entity:
            raise ValueError(
                "SUPERSEDES must connect revisions "
                "of the same logical entity"
            )

    relations = tuple(
        Relation(
            source=revision,
            kind=DERIVED_FROM,
            target=source,
        )
        for source in sources
    ) + tuple(
        Relation(
            source=revision,
            kind=SUPERSEDES,
            target=older,
        )
        for older in previous
    )

    return RelationGraph(
        relations=relations,
    )


def superseded_by(
    graph: RelationGraph,
    value: MaterializedRef,
) -> tuple[RevisionRef, ...]:
    """Return revisions that canonically supersede ``value``.

    ``SUPERSEDED_BY`` is an inverse graph query, not a persisted relation kind.
    """

    if not isinstance(
        graph,
        RelationGraph,
    ):
        raise TypeError(
            "graph must be a RelationGraph"
        )

    revision = materialized_revision(
        value
    )

    result: list[RevisionRef] = []
    seen: set[RevisionRef] = set()

    for relation in graph.incoming(
        revision,
        kind=SUPERSEDES,
    ):
        source = relation.source

        if not isinstance(
            source,
            RevisionRef,
        ):
            raise ValueError(
                "SUPERSEDES relation source "
                "must be a RevisionRef"
            )

        if (
            source.entity
            != revision.entity
        ):
            raise ValueError(
                "SUPERSEDES must connect revisions "
                "of the same logical entity"
            )

        if source in seen:
            continue

        seen.add(
            source
        )

        result.append(
            source
        )

    return tuple(
        result
    )


def combine_provenance(
    *graphs: RelationGraph,
) -> RelationGraph:
    """Combine canonical provenance fragments in deterministic order."""

    relations: list[Relation] = []

    for graph in graphs:
        if not isinstance(
            graph,
            RelationGraph,
        ):
            raise TypeError(
                "all provenance fragments must "
                "be RelationGraph objects"
            )

        relations.extend(
            graph.relations
        )

    return RelationGraph(
        relations=tuple(
            relations
        ),
    )


__all__ = [
    "MaterializedRef",
    "combine_provenance",
    "materialized_lineage_relations",
    "materialized_revision",
    "run_io_relations",
    "run_ref",
    "superseded_by",
]
