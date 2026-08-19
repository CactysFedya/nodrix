"""Immutable final records for persistent Nodrix Runs.

``run.json`` is the final historical record of one completed Run.

Unlike ``status.json`` it is never replaced.  Publication happens only after a
complete temporary file has been written and fsynced.  The temporary file is
then atomically linked into place without overwrite semantics.

The exact domain-specific Definition and Plan payload snapshots are stored by
the provenance layer.  ``run.json`` records their canonical identities and the
final canonical ExecutionRecord.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from nodrix.model.executions import (
    ExecutionRecord,
)
from nodrix.model.history import (
    record_run,
)
from nodrix.model.runs import (
    RunRecord,
)
from nodrix.run_session import (
    RunSession,
)


RUN_RECORD_API_VERSION = (
    "nodrix.run-record/v1"
)
RUN_RECORD_KIND = "RunRecord"


class RunRecordStorageError(RuntimeError):
    """Base error for persistent final Run records."""


class RunRecordCorruptionError(
    RunRecordStorageError
):
    """Existing run.json violates the final Run record contract."""


def _timestamp_text(
    value: datetime,
) -> str:
    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError(
            "timestamp must be a datetime"
        )

    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            "timestamp must be timezone-aware"
        )

    return (
        value
        .astimezone(timezone.utc)
        .isoformat(
            timespec="microseconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


def _json_value(
    value: Any,
) -> Any:
    """Convert canonical record values to deterministic JSON data."""

    if isinstance(
        value,
        Enum,
    ):
        return value.value

    if isinstance(
        value,
        datetime,
    ):
        return _timestamp_text(
            value
        )

    if isinstance(
        value,
        Path,
    ):
        return str(value)

    if value is None or isinstance(
        value,
        (
            bool,
            int,
            str,
        ),
    ):
        return value

    if isinstance(
        value,
        float,
    ):
        if not math.isfinite(
            value
        ):
            raise ValueError(
                "final Run record cannot contain "
                "non-finite floats"
            )

        return value

    if isinstance(
        value,
        Mapping,
    ):
        result: dict[
            str,
            Any,
        ] = {}

        for key, item in value.items():
            if not isinstance(
                key,
                str,
            ):
                raise TypeError(
                    "final Run record mapping keys "
                    "must be strings"
                )

            result[key] = (
                _json_value(
                    item
                )
            )

        return result

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        return [
            _json_value(
                item
            )
            for item in value
        ]

    raise TypeError(
        "final Run record contains unsupported "
        f"value {type(value).__name__}"
    )


def run_record_document(
    run: RunRecord,
) -> dict[str, Any]:
    """Serialize one canonical RunRecord without duplicating Plan payload."""

    if not isinstance(
        run,
        RunRecord,
    ):
        raise TypeError(
            "run must be a RunRecord"
        )

    execution = (
        run.execution
    )
    plan = execution.plan
    operation = plan.operation

    document = {
        "apiVersion": (
            RUN_RECORD_API_VERSION
        ),
        "kind": (
            RUN_RECORD_KIND
        ),
        "runId": (
            run.run_id
        ),
        "execution": {
            "executionId": (
                execution.execution_id
            ),
            "executor": (
                execution.executor
            ),
            "state": (
                execution.state.value
            ),
            "terminal": (
                execution.terminal
            ),
            "successful": (
                execution.successful
            ),
            "startedAt": (
                _timestamp_text(
                    execution.started_at
                )
            ),
            "finishedAt": (
                _timestamp_text(
                    execution.finished_at
                )
            ),
            "details": (
                _json_value(
                    execution.details
                )
            ),
            "plan": {
                "planId": (
                    plan.plan_id
                ),
                "kind": (
                    plan.kind_name
                ),
                "operation": {
                    "kind": (
                        operation.kind_name
                    ),
                    "subject": (
                        operation
                        .subject
                        .canonical
                    ),
                    "subjectRevision": (
                        operation
                        .subject_revision
                        .canonical
                        if (
                            operation
                            .subject_revision
                            is not None
                        )
                        else None
                    ),
                    "parameters": (
                        _json_value(
                            operation.parameters
                        )
                    ),
                },
                "subjectRevision": (
                    plan
                    .subject_revision
                    .canonical
                ),
            },
        },
        "summary": (
            _json_value(
                run.summary
            )
        ),
        "metadata": (
            _json_value(
                run.metadata
            )
        ),
    }

    # Validate the whole document now, before filesystem publication.
    json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    return document


def _validate_document(
    document: Any,
    *,
    session: RunSession,
) -> None:
    if not isinstance(
        document,
        dict,
    ):
        raise RunRecordCorruptionError(
            "run.json must contain a JSON object"
        )

    if (
        document.get(
            "apiVersion"
        )
        != RUN_RECORD_API_VERSION
    ):
        raise RunRecordCorruptionError(
            "unsupported run.json apiVersion"
        )

    if (
        document.get("kind")
        != RUN_RECORD_KIND
    ):
        raise RunRecordCorruptionError(
            "invalid run.json kind"
        )

    if (
        document.get("runId")
        != session.run_id
    ):
        raise RunRecordCorruptionError(
            "run.json belongs to a different Run"
        )

    execution = document.get(
        "execution"
    )

    if not isinstance(
        execution,
        dict,
    ):
        raise RunRecordCorruptionError(
            "run.json execution must be an object"
        )

    if (
        execution.get("terminal")
        is not True
    ):
        raise RunRecordCorruptionError(
            "run.json must contain a terminal execution"
        )

    state = execution.get(
        "state"
    )

    if state not in {
        "stopped",
        "completed",
        "failed",
        "cancelled",
    }:
        raise RunRecordCorruptionError(
            "run.json contains an invalid terminal state"
        )

    successful = (
        execution.get(
            "successful"
        )
    )

    expected_success = (
        state
        in {
            "stopped",
            "completed",
        }
    )

    if (
        successful
        is not expected_success
    ):
        raise RunRecordCorruptionError(
            "run.json successful flag does not "
            "match execution state"
        )

    plan = execution.get(
        "plan"
    )

    if not isinstance(
        plan,
        dict,
    ):
        raise RunRecordCorruptionError(
            "run.json execution.plan must be an object"
        )

    if (
        plan.get("planId")
        != session.plan_id
    ):
        raise RunRecordCorruptionError(
            "run.json belongs to a different Plan"
        )

    for field_name in (
        "executionId",
        "executor",
        "startedAt",
        "finishedAt",
    ):
        value = execution.get(
            field_name
        )

        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):
            raise RunRecordCorruptionError(
                "run.json execution."
                f"{field_name} must be non-empty"
            )

    if not isinstance(
        document.get("summary"),
        dict,
    ):
        raise RunRecordCorruptionError(
            "run.json summary must be an object"
        )

    if not isinstance(
        document.get("metadata"),
        dict,
    ):
        raise RunRecordCorruptionError(
            "run.json metadata must be an object"
        )


class RunRecordStore:
    """Create and read the immutable final record of one persistent Run."""

    def __init__(
        self,
        session: RunSession,
    ) -> None:
        if not isinstance(
            session,
            RunSession,
        ):
            raise TypeError(
                "session must be a RunSession"
            )

        self._session = (
            session
        )

    @property
    def run_id(self) -> str:
        return (
            self._session.run_id
        )

    @property
    def path(self) -> Path:
        return (
            self._session.directory
            / "run.json"
        )

    def read(
        self,
    ) -> dict[str, Any] | None:
        """Read and validate the immutable final record."""

        if not self.path.exists():
            return None

        if not self.path.is_file():
            raise RunRecordCorruptionError(
                "run.json exists but is not a file"
            )

        try:
            with self.path.open(
                "r",
                encoding="utf-8",
            ) as stream:
                document = json.load(
                    stream
                )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RunRecordCorruptionError(
                "run.json contains invalid JSON"
            ) from exc

        _validate_document(
            document,
            session=self._session,
        )

        return document

    def create(
        self,
        execution: ExecutionRecord,
        *,
        summary: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RunRecord:
        """Publish one final RunRecord exactly once."""

        if not isinstance(
            execution,
            ExecutionRecord,
        ):
            raise TypeError(
                "execution must be an ExecutionRecord"
            )

        run = record_run(
            execution,
            run_id=self._session.run_id,
            summary=summary,
            metadata=metadata,
        )

        if (
            run.plan.plan_id
            != self._session.plan_id
        ):
            raise ValueError(
                "ExecutionRecord belongs to a different "
                "RunSession PlanRecord"
            )

        document = (
            run_record_document(
                run
            )
        )

        encoded = (
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode(
            "utf-8"
        )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.path.parent,
                prefix=".run.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(
                    stream.name
                )

                stream.write(
                    encoded
                )
                stream.flush()
                os.fsync(
                    stream.fileno()
                )

            # os.link publishes without replacement semantics:
            # if run.json already exists, FileExistsError is raised.
            os.link(
                temporary_path,
                self.path,
            )
        finally:
            if (
                temporary_path
                is not None
            ):
                try:
                    temporary_path.unlink(
                        missing_ok=True
                    )
                except OSError:
                    pass

        return run


__all__ = [
    "RUN_RECORD_API_VERSION",
    "RUN_RECORD_KIND",
    "RunRecordCorruptionError",
    "RunRecordStorageError",
    "RunRecordStore",
    "run_record_document",
]
