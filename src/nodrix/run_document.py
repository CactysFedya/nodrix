"""Canonical Nodrix Run document serialization and local storage.

The canonical Python object model remains independent from persistence.
This module projects a completed RunRecord and its provenance graph into the
versioned ``nodrix.run/v1`` document format.

Canonical run documents are stored at::

    .nodrix/runs/<run-id>/run.json

The layout intentionally coexists with the legacy run loader while establishing
a stable format for future Nodrix execution history.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from .model import (
    EntityRef,
    RecordRef,
    RelationGraph,
    RevisionRef,
    RunRecord,
    execution_record_ref,
    plan_record_ref,
    run_record_ref,
)


from .storage_layout import StorageLayout


RUN_DOCUMENT_SCHEMA = "nodrix.run/v1"
RUN_DOCUMENT_KIND = "Run"


def _datetime_text(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("canonical timestamp must be a datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "canonical timestamp must be timezone-aware"
        )

    normalized = value.astimezone(timezone.utc)

    return normalized.isoformat().replace(
        "+00:00",
        "Z",
    )


def _json_value(value: Any) -> Any:
    """Convert supported canonical values into deterministic JSON values."""

    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                "canonical run documents do not allow "
                "NaN or infinite floating-point values"
            )
        return value

    if isinstance(value, str):
        return value

    if isinstance(
        value,
        (EntityRef, RevisionRef, RecordRef),
    ):
        return str(value)

    if isinstance(value, datetime):
        return _datetime_text(value)

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}

        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    "canonical JSON mapping keys must be strings"
                )

            result[key] = _json_value(item)

        return result

    if isinstance(value, (tuple, list)):
        return [
            _json_value(item)
            for item in value
        ]

    raise TypeError(
        "value is not supported by canonical run JSON: "
        f"{type(value).__name__}"
    )


def run_to_document(
    run: RunRecord,
    *,
    provenance: RelationGraph | None = None,
) -> dict[str, Any]:
    """Project one RunRecord into a ``nodrix.run/v1`` document."""

    if not isinstance(run, RunRecord):
        raise TypeError(
            "run must be a RunRecord"
        )

    if provenance is not None and not isinstance(
        provenance,
        RelationGraph,
    ):
        raise TypeError(
            "provenance must be a RelationGraph or None"
        )

    started_at = run.started_at
    finished_at = run.finished_at

    if started_at is None or finished_at is None:
        raise ValueError(
            "canonical Run document requires complete timestamps"
        )

    duration_seconds = (
        finished_at - started_at
    ).total_seconds()

    relations = (
        ()
        if provenance is None
        else provenance.relations
    )

    return {
        "schema": RUN_DOCUMENT_SCHEMA,
        "kind": RUN_DOCUMENT_KIND,
        "id": run.run_id,
        "ref": str(
            run_record_ref(run)
        ),
        # Kept top-level for compatibility with the existing run listing code.
        "status": run.state.value,
        "successful": run.successful,
        "duration_seconds": duration_seconds,
        "subject": {
            "entity": str(run.subject),
            "revision": str(
                run.subject_revision
            ),
        },
        "operation": {
            "kind": run.operation.kind_name,
            "parameters": _json_value(
                run.operation.parameters
            ),
        },
        "plan": {
            "id": run.plan.plan_id,
            "ref": str(
                plan_record_ref(run.plan)
            ),
            "kind": run.plan.kind_name,
            "metadata": _json_value(
                run.plan.metadata
            ),
        },
        "execution": {
            "id": run.execution_id,
            "ref": str(
                execution_record_ref(
                    run.execution
                )
            ),
            "executor": run.execution.executor,
            "state": run.state.value,
            "started_at": _datetime_text(
                started_at
            ),
            "finished_at": _datetime_text(
                finished_at
            ),
            "details": _json_value(
                run.execution.details
            ),
        },
        "summary": _json_value(
            run.summary
        ),
        "metadata": _json_value(
            run.metadata
        ),
        "relations": [
            {
                "source": str(
                    relation.source
                ),
                "kind": relation.kind_name,
                "target": str(
                    relation.target
                ),
                "metadata": _json_value(
                    relation.metadata
                ),
            }
            for relation in relations
        ],
    }


def dumps_run_document(
    run: RunRecord,
    *,
    provenance: RelationGraph | None = None,
) -> str:
    """Serialize one canonical Run document deterministically."""

    document = run_to_document(
        run,
        provenance=provenance,
    )

    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )


def canonical_run_root(
    project: str | Path = ".",
) -> Path:
    """Return the canonical local Run storage root."""

    return StorageLayout(
        project
    ).runs_root


def canonical_run_directory(
    run: RunRecord,
    *,
    project: str | Path = ".",
) -> Path:
    """Return the storage directory for one Run.

    RecordRef validation also guarantees that the run id is safe as one
    filesystem path component.
    """

    ref = run_record_ref(run)

    return (
        canonical_run_root(project)
        / ref.record_id
    )


def _atomic_write_text(
    path: Path,
    text: str,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".run.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

            temporary_path = Path(
                handle.name
            )

        os.replace(
            temporary_path,
            path,
        )

        temporary_path = None

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink()


def write_run_document(
    run: RunRecord,
    *,
    project: str | Path = ".",
    provenance: RelationGraph | None = None,
) -> Path:
    """Persist one immutable ``nodrix.run/v1`` document.

    Repeating the exact same write is idempotent.  Attempting to replace an
    existing run id with different content is rejected because Run records are
    historical immutable evidence.
    """

    text = dumps_run_document(
        run,
        provenance=provenance,
    )

    directory = canonical_run_directory(
        run,
        project=project,
    )

    path = directory / "run.json"

    if path.exists():
        existing = path.read_text(
            encoding="utf-8"
        )

        if existing == text:
            return path

        raise FileExistsError(
            "canonical Run document already exists "
            f"with different content: {path}"
        )

    _atomic_write_text(
        path,
        text,
    )

    return path


__all__ = [
    "RUN_DOCUMENT_KIND",
    "RUN_DOCUMENT_SCHEMA",
    "canonical_run_directory",
    "canonical_run_root",
    "dumps_run_document",
    "run_to_document",
    "write_run_document",
]
