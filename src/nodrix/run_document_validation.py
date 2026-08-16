"""Validation and loading of canonical ``nodrix.run/v1`` documents.

The writer in ``nodrix.run_document`` owns serialization and local persistence.
This module owns the inverse boundary: untrusted JSON is validated before it is
treated as canonical Nodrix history.

Legacy run formats are intentionally not handled here.  Compatibility remains
owned by ``nodrix.runs``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .model import (
    CONSUMES,
    DERIVED_FROM,
    EXECUTED_AS,
    PRODUCES,
    RECORDED_AS,
    SUPERSEDES,
    EntityRef,
    ExecutionState,
    OperationKind,
    PlanKind,
    RecordRef,
    Relation,
    RelationGraph,
    RevisionRef,
    parse_canonical_ref,
)
from .run_document import (
    RUN_DOCUMENT_KIND,
    RUN_DOCUMENT_SCHEMA,
    canonical_run_root,
)


class RunDocumentValidationError(ValueError):
    """A ``nodrix.run/v1`` document violates a canonical invariant."""

    def __init__(
        self,
        path: str,
        message: str,
    ) -> None:
        self.path = path
        self.message = message
        super().__init__(
            f"{path}: {message}"
            if path
            else message
        )


@dataclass(frozen=True, slots=True)
class ValidatedRunDocument:
    """Validated semantic view of one canonical Run document."""

    run_id: str
    run_ref: RecordRef

    subject: EntityRef
    subject_revision: RevisionRef

    operation_kind: OperationKind

    plan_ref: RecordRef
    plan_kind: PlanKind

    execution_ref: RecordRef
    executor: str
    state: ExecutionState

    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    successful: bool

    relations: RelationGraph

    document: Mapping[str, Any] = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "document",
            MappingProxyType(
                dict(self.document)
            ),
        )


def _error(
    path: str,
    message: str,
) -> RunDocumentValidationError:
    return RunDocumentValidationError(
        path,
        message,
    )


def _mapping(
    value: Any,
    *,
    path: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(
            path,
            "must be an object",
        )

    for key in value:
        if not isinstance(key, str):
            raise _error(
                path,
                "object keys must be strings",
            )

    return value


def _sequence(
    value: Any,
    *,
    path: str,
) -> list[Any] | tuple[Any, ...]:
    if not isinstance(
        value,
        (list, tuple),
    ):
        raise _error(
            path,
            "must be an array",
        )

    return value


def _required_text(
    value: Any,
    *,
    path: str,
) -> str:
    if not isinstance(value, str):
        raise _error(
            path,
            "must be a string",
        )

    normalized = value.strip()

    if not normalized:
        raise _error(
            path,
            "must be non-empty",
        )

    return normalized


def _required_bool(
    value: Any,
    *,
    path: str,
) -> bool:
    if not isinstance(value, bool):
        raise _error(
            path,
            "must be a boolean",
        )

    return value


def _number(
    value: Any,
    *,
    path: str,
) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float),
    ):
        raise _error(
            path,
            "must be a finite number",
        )

    result = float(value)

    if not math.isfinite(result):
        raise _error(
            path,
            "must be a finite number",
        )

    return result


def _timestamp(
    value: Any,
    *,
    path: str,
) -> datetime:
    text = _required_text(
        value,
        path=path,
    )

    normalized = (
        text[:-1] + "+00:00"
        if text.endswith("Z")
        else text
    )

    try:
        parsed = datetime.fromisoformat(
            normalized
        )
    except ValueError as exc:
        raise _error(
            path,
            "must be a valid ISO 8601 timestamp",
        ) from exc

    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise _error(
            path,
            "must be timezone-aware",
        )

    return parsed


def _canonical_ref(
    value: Any,
    *,
    path: str,
):
    text = _required_text(
        value,
        path=path,
    )

    try:
        return parse_canonical_ref(
            text
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            path,
            "must be a valid canonical Nodrix reference",
        ) from exc


def _record_ref(
    value: Any,
    *,
    path: str,
    kind: str,
    record_id: str,
) -> RecordRef:
    ref = _canonical_ref(
        value,
        path=path,
    )

    if not isinstance(
        ref,
        RecordRef,
    ):
        raise _error(
            path,
            "must reference a historical record",
        )

    if ref.kind != kind:
        raise _error(
            path,
            f"must reference record kind {kind!r}",
        )

    if ref.record_id != record_id:
        raise _error(
            path,
            f"must reference record id {record_id!r}",
        )

    return ref


def _relations(
    value: Any,
) -> RelationGraph:
    items = _sequence(
        value,
        path="relations",
    )

    relations: list[Relation] = []

    for index, raw in enumerate(items):
        path = f"relations[{index}]"

        item = _mapping(
            raw,
            path=path,
        )

        source = _canonical_ref(
            item.get("source"),
            path=f"{path}.source",
        )

        target = _canonical_ref(
            item.get("target"),
            path=f"{path}.target",
        )

        kind = _required_text(
            item.get("kind"),
            path=f"{path}.kind",
        )

        metadata = _mapping(
            item.get(
                "metadata",
                {},
            ),
            path=f"{path}.metadata",
        )

        try:
            relation = Relation(
                source=source,
                kind=kind,
                target=target,
                metadata=metadata,
            )
        except (TypeError, ValueError) as exc:
            raise _error(
                path,
                str(exc),
            ) from exc

        relations.append(
            relation
        )

    return RelationGraph(
        relations=tuple(relations),
    )


def _validate_lifecycle_relation_consistency(
    graph: RelationGraph,
    *,
    plan_ref: RecordRef,
    execution_ref: RecordRef,
    run_ref: RecordRef,
) -> None:
    executed = graph.outgoing(
        plan_ref,
        kind=EXECUTED_AS,
    )

    for relation in executed:
        if relation.target != execution_ref:
            raise _error(
                "relations",
                "executed_as relation from this plan "
                "must target this execution",
            )

    recorded = graph.outgoing(
        execution_ref,
        kind=RECORDED_AS,
    )

    for relation in recorded:
        if relation.target != run_ref:
            raise _error(
                "relations",
                "recorded_as relation from this execution "
                "must target this run",
            )


def _validate_materialized_provenance_consistency(
    graph: RelationGraph,
    *,
    run_ref: RecordRef,
) -> None:
    """Validate canonical materialized provenance relation semantics."""

    for relation in graph.relations:
        if relation.kind in (
            CONSUMES,
            PRODUCES,
        ):
            if relation.source != run_ref:
                raise _error(
                    "relations",
                    f"{relation.kind_name} relation "
                    "must originate from this run",
                )

            if not isinstance(
                relation.target,
                RevisionRef,
            ):
                raise _error(
                    "relations",
                    f"{relation.kind_name} relation "
                    "must target a RevisionRef",
                )

        elif relation.kind == DERIVED_FROM:
            if not isinstance(
                relation.source,
                RevisionRef,
            ) or not isinstance(
                relation.target,
                RevisionRef,
            ):
                raise _error(
                    "relations",
                    "derived_from must connect "
                    "RevisionRef objects",
                )

            if (
                relation.source
                == relation.target
            ):
                raise _error(
                    "relations",
                    "a revision cannot be "
                    "derived from itself",
                )

        elif relation.kind == SUPERSEDES:
            if not isinstance(
                relation.source,
                RevisionRef,
            ) or not isinstance(
                relation.target,
                RevisionRef,
            ):
                raise _error(
                    "relations",
                    "supersedes must connect "
                    "RevisionRef objects",
                )

            if (
                relation.source
                == relation.target
            ):
                raise _error(
                    "relations",
                    "a revision cannot "
                    "supersede itself",
                )

            if (
                relation.source.entity
                != relation.target.entity
            ):
                raise _error(
                    "relations",
                    "supersedes must connect revisions "
                    "of the same logical entity",
                )


def validate_run_document(
    document: Mapping[str, Any],
) -> ValidatedRunDocument:
    """Validate one parsed ``nodrix.run/v1`` document."""

    root = _mapping(
        document,
        path="",
    )

    schema = _required_text(
        root.get("schema"),
        path="schema",
    )

    if schema != RUN_DOCUMENT_SCHEMA:
        raise _error(
            "schema",
            f"expected {RUN_DOCUMENT_SCHEMA!r}",
        )

    kind = _required_text(
        root.get("kind"),
        path="kind",
    )

    if kind != RUN_DOCUMENT_KIND:
        raise _error(
            "kind",
            f"expected {RUN_DOCUMENT_KIND!r}",
        )

    run_id = _required_text(
        root.get("id"),
        path="id",
    )

    try:
        expected_run_ref = RecordRef(
            kind="run",
            record_id=run_id,
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            "id",
            str(exc),
        ) from exc

    run_ref = _record_ref(
        root.get("ref"),
        path="ref",
        kind="run",
        record_id=run_id,
    )

    status_text = _required_text(
        root.get("status"),
        path="status",
    )

    try:
        state = ExecutionState.parse(
            status_text
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            "status",
            str(exc),
        ) from exc

    if not state.terminal:
        raise _error(
            "status",
            "canonical Run documents require a terminal state",
        )

    successful = _required_bool(
        root.get("successful"),
        path="successful",
    )

    if successful != state.successful:
        raise _error(
            "successful",
            "does not match terminal execution state",
        )

    duration_seconds = _number(
        root.get("duration_seconds"),
        path="duration_seconds",
    )

    if duration_seconds < 0:
        raise _error(
            "duration_seconds",
            "cannot be negative",
        )

    subject = _mapping(
        root.get("subject"),
        path="subject",
    )

    subject_entity_ref = _canonical_ref(
        subject.get("entity"),
        path="subject.entity",
    )

    if not isinstance(
        subject_entity_ref,
        EntityRef,
    ):
        raise _error(
            "subject.entity",
            "must be an EntityRef",
        )

    subject_revision_ref = _canonical_ref(
        subject.get("revision"),
        path="subject.revision",
    )

    if not isinstance(
        subject_revision_ref,
        RevisionRef,
    ):
        raise _error(
            "subject.revision",
            "must be a RevisionRef",
        )

    if (
        subject_revision_ref.entity
        != subject_entity_ref
    ):
        raise _error(
            "subject.revision",
            "must reference subject.entity",
        )

    operation = _mapping(
        root.get("operation"),
        path="operation",
    )

    operation_kind_text = _required_text(
        operation.get("kind"),
        path="operation.kind",
    )

    try:
        operation_kind = OperationKind.parse(
            operation_kind_text
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            "operation.kind",
            str(exc),
        ) from exc

    _mapping(
        operation.get(
            "parameters",
            {},
        ),
        path="operation.parameters",
    )

    plan = _mapping(
        root.get("plan"),
        path="plan",
    )

    plan_id = _required_text(
        plan.get("id"),
        path="plan.id",
    )

    plan_ref = _record_ref(
        plan.get("ref"),
        path="plan.ref",
        kind="plan",
        record_id=plan_id,
    )

    plan_kind_text = _required_text(
        plan.get("kind"),
        path="plan.kind",
    )

    try:
        plan_kind = PlanKind.parse(
            plan_kind_text
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            "plan.kind",
            str(exc),
        ) from exc

    _mapping(
        plan.get(
            "metadata",
            {},
        ),
        path="plan.metadata",
    )

    execution = _mapping(
        root.get("execution"),
        path="execution",
    )

    execution_id = _required_text(
        execution.get("id"),
        path="execution.id",
    )

    execution_ref = _record_ref(
        execution.get("ref"),
        path="execution.ref",
        kind="execution",
        record_id=execution_id,
    )

    executor = _required_text(
        execution.get("executor"),
        path="execution.executor",
    )

    execution_state_text = _required_text(
        execution.get("state"),
        path="execution.state",
    )

    try:
        execution_state = ExecutionState.parse(
            execution_state_text
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            "execution.state",
            str(exc),
        ) from exc

    if execution_state != state:
        raise _error(
            "execution.state",
            "must match top-level status",
        )

    started_at = _timestamp(
        execution.get("started_at"),
        path="execution.started_at",
    )

    finished_at = _timestamp(
        execution.get("finished_at"),
        path="execution.finished_at",
    )

    if finished_at < started_at:
        raise _error(
            "execution.finished_at",
            "cannot be earlier than execution.started_at",
        )

    actual_duration = (
        finished_at - started_at
    ).total_seconds()

    if not math.isclose(
        duration_seconds,
        actual_duration,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise _error(
            "duration_seconds",
            "must match execution timestamps",
        )

    _mapping(
        execution.get(
            "details",
            {},
        ),
        path="execution.details",
    )

    _mapping(
        root.get(
            "summary",
            {},
        ),
        path="summary",
    )

    _mapping(
        root.get(
            "metadata",
            {},
        ),
        path="metadata",
    )

    relation_graph = _relations(
        root.get(
            "relations",
            [],
        )
    )

    _validate_lifecycle_relation_consistency(
        relation_graph,
        plan_ref=plan_ref,
        execution_ref=execution_ref,
        run_ref=run_ref,
    )

    _validate_materialized_provenance_consistency(
        relation_graph,
        run_ref=run_ref,
    )

    if run_ref != expected_run_ref:
        raise _error(
            "ref",
            "must match the canonical Run identity",
        )

    return ValidatedRunDocument(
        run_id=run_id,
        run_ref=run_ref,
        subject=subject_entity_ref,
        subject_revision=subject_revision_ref,
        operation_kind=operation_kind,
        plan_ref=plan_ref,
        plan_kind=plan_kind,
        execution_ref=execution_ref,
        executor=executor,
        state=state,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
        successful=successful,
        relations=relation_graph,
        document=root,
    )


def loads_run_document(
    text: str,
) -> ValidatedRunDocument:
    """Parse and validate canonical Run JSON text."""

    if not isinstance(text, str):
        raise TypeError(
            "Run document text must be a string"
        )

    try:
        document = json.loads(
            text
        )
    except json.JSONDecodeError as exc:
        raise RunDocumentValidationError(
            "",
            f"invalid JSON: {exc.msg}",
        ) from exc

    if not isinstance(
        document,
        Mapping,
    ):
        raise RunDocumentValidationError(
            "",
            "Run document root must be an object",
        )

    return validate_run_document(
        document
    )


def read_run_document(
    path: str | Path,
) -> ValidatedRunDocument:
    """Read and validate one canonical ``run.json`` file."""

    run_path = (
        Path(path)
        .expanduser()
        .resolve()
    )

    try:
        text = run_path.read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        raise OSError(
            f"cannot read Run document {run_path}: {exc}"
        ) from exc

    return loads_run_document(
        text
    )


def load_canonical_run(
    run_id: str,
    *,
    project: str | Path = ".",
) -> ValidatedRunDocument:
    """Load one exact canonical Run from local Nodrix storage."""

    try:
        ref = RecordRef(
            kind="run",
            record_id=run_id,
        )
    except (TypeError, ValueError) as exc:
        raise RunDocumentValidationError(
            "run_id",
            str(exc),
        ) from exc

    path = (
        canonical_run_root(project)
        / ref.record_id
        / "run.json"
    )

    validated = read_run_document(
        path
    )

    if validated.run_id != ref.record_id:
        raise RunDocumentValidationError(
            "id",
            "stored Run id does not match requested Run id",
        )

    return validated


__all__ = [
    "RunDocumentValidationError",
    "ValidatedRunDocument",
    "load_canonical_run",
    "loads_run_document",
    "read_run_document",
    "validate_run_document",
]
