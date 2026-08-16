"""Canonical provenance helpers for Run inputs and outputs.

A Run consumes and produces immutable revisions, not filesystem paths and not
mutable logical entity names.

DatasetRecord and ArtifactRecord are convenient materialized records, while a
raw RevisionRef allows future user-defined record types to participate without
changing the canonical provenance model.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeAlias

from .data import ArtifactRecord, DatasetRecord
from .identity import RevisionRef
from .references import RecordRef
from .relations import (
    CONSUMES,
    PRODUCES,
    Relation,
    RelationGraph,
)
from .runs import RunRecord


MaterializedRef: TypeAlias = (
    RevisionRef
    | DatasetRecord
    | ArtifactRecord
)


def _revision_of(
    value: MaterializedRef,
) -> RevisionRef:
    if isinstance(value, RevisionRef):
        return value

    if isinstance(
        value,
        (DatasetRecord, ArtifactRecord),
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
        (str, bytes),
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
        revision = _revision_of(value)

        if revision in seen:
            continue

        seen.add(revision)
        result.append(revision)

    return tuple(result)


def run_ref(run: RunRecord) -> RecordRef:
    """Return the canonical historical reference of one Run."""

    if not isinstance(run, RunRecord):
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

    canonical_run = run_ref(run)

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
                "all provenance fragments must be RelationGraph objects"
            )

        relations.extend(
            graph.relations
        )

    return RelationGraph(
        relations=tuple(relations),
    )


__all__ = [
    "MaterializedRef",
    "combine_provenance",
    "run_io_relations",
    "run_ref",
]
