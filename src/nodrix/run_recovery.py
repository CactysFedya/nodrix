"""Read-only recovery and provenance integrity inspection for Nodrix Runs.

This module deliberately does not restart, stop, attach to, or otherwise own
processes. Process ownership belongs to the later supervisor/runtime layer.

Recovery answers a narrower question:

    "What durable state is present for this Run, and is it internally
    consistent?"

A non-terminal Run is classified as ``active-or-unknown`` by default.  A caller
that already knows no live owner exists may pass ``assume_inactive=True``; only
then is the same durable state classified as ``interrupted``.

This distinction avoids a false stale heuristic based solely on status
timestamps. ``status.json`` is intentionally not rewritten for unchanged
observations and therefore is not a heartbeat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Literal

from nodrix.run_session import (
    RUN_LAYOUT_SCHEMA,
    RUN_SESSION_SCHEMA,
)


HEALTHY_TERMINAL = "healthy-terminal"
ACTIVE_OR_UNKNOWN = "active-or-unknown"
FAILED_BEFORE_START = "failed-before-start"
INTERRUPTED = "interrupted"
INCOMPLETE = "incomplete"
CORRUPTED = "corrupted"

RunRecoveryClassification = Literal[
    "healthy-terminal",
    "active-or-unknown",
    "failed-before-start",
    "interrupted",
    "incomplete",
    "corrupted",
]

IssueSeverity = Literal[
    "warning",
    "error",
]

_TERMINAL_STATES = {
    "stopped",
    "completed",
    "failed",
    "cancelled",
}

_KNOWN_STATES = {
    "created",
    "prepared",
    "running",
    "stopping",
    *_TERMINAL_STATES,
}

_INCOMPLETE_CODES = {
    "REC101",
    "REC102",
    "REC103",
    "REC104",
    "REC105",
    "REC106",
}


@dataclass(
    frozen=True,
    slots=True,
)
class RunRecoveryIssue:
    """One deterministic Run integrity/recovery diagnostic."""

    severity: IssueSeverity
    code: str
    path: str
    message: str


@dataclass(
    frozen=True,
    slots=True,
)
class RunRecoveryReport:
    """Read-only interpretation of one persisted Run directory."""

    directory: Path
    run_id: str | None
    plan_id: str | None
    classification: RunRecoveryClassification
    recovered_state: str | None
    execution_id: str | None
    event_count: int
    final_record_present: bool
    temporary_files: tuple[str, ...]
    issues: tuple[
        RunRecoveryIssue,
        ...,
    ]

    @property
    def corrupted(self) -> bool:
        return (
            self.classification
            == CORRUPTED
        )

    @property
    def terminal(self) -> bool:
        return (
            self.recovered_state
            in _TERMINAL_STATES
        )


def _reject_json_constant(
    value: str,
) -> None:
    raise ValueError(
        "non-standard JSON numeric "
        f"constant {value!r}"
    )


def _load_json(
    path: Path,
) -> dict[str, Any]:
    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as stream:
            document = json.load(
                stream,
                parse_constant=(
                    _reject_json_constant
                ),
            )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise ValueError(
            f"{path.name} contains invalid JSON"
        ) from exc

    if not isinstance(
        document,
        dict,
    ):
        raise ValueError(
            f"{path.name} must contain "
            "a JSON object"
        )

    return document


def _load_json_line(
    value: str,
    *,
    path: Path,
    line_number: int,
) -> dict[str, Any]:
    try:
        document = json.loads(
            value,
            parse_constant=(
                _reject_json_constant
            ),
        )
    except (
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise ValueError(
            f"{path.name}:{line_number} "
            "contains invalid JSON"
        ) from exc

    if not isinstance(
        document,
        dict,
    ):
        raise ValueError(
            f"{path.name}:{line_number} "
            "must contain a JSON object"
        )

    return document


def _parse_timestamp(
    value: Any,
    *,
    field_name: str,
) -> datetime:
    if not isinstance(
        value,
        str,
    ):
        raise ValueError(
            f"{field_name} must be a string"
        )

    candidate = (
        value[:-1] + "+00:00"
        if value.endswith("Z")
        else value
    )

    try:
        result = (
            datetime.fromisoformat(
                candidate
            )
        )
    except ValueError as exc:
        raise ValueError(
            f"{field_name} is not "
            "a valid ISO timestamp"
        ) from exc

    if (
        result.tzinfo is None
        or result.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be timezone-aware"
        )

    return result


def _text_field(
    document: dict[str, Any],
    name: str,
    *,
    source: str,
) -> str:
    value = document.get(
        name
    )

    if (
        not isinstance(
            value,
            str,
        )
        or not value.strip()
    ):
        raise ValueError(
            f"{source}.{name} must be "
            "a non-empty string"
        )

    return value.strip()


def _add(
    issues: list[
        RunRecoveryIssue
    ],
    severity: IssueSeverity,
    code: str,
    path: str,
    message: str,
) -> None:
    issues.append(
        RunRecoveryIssue(
            severity=severity,
            code=code,
            path=path,
            message=message,
        )
    )


def _load_optional(
    directory: Path,
    filename: str,
    *,
    missing_code: str,
    issues: list[
        RunRecoveryIssue
    ],
) -> dict[str, Any] | None:
    path = (
        directory
        / filename
    )

    if not path.exists():
        _add(
            issues,
            "warning",
            missing_code,
            filename,
            f"{filename} is missing",
        )
        return None

    if not path.is_file():
        _add(
            issues,
            "error",
            "REC201",
            filename,
            f"{filename} exists but "
            "is not a regular file",
        )
        return None

    try:
        return _load_json(
            path
        )
    except ValueError as exc:
        _add(
            issues,
            "error",
            "REC202",
            filename,
            str(exc),
        )
        return None



def _check_identity(
    document: dict[str, Any] | None,
    *,
    filename: str,
    run_id: str,
    plan_id: str,
    issues: list[
        RunRecoveryIssue
    ],
    require_plan_id: bool = True,
) -> None:
    """Validate identities actually promised by the file's contract."""

    if document is None:
        return

    if (
        document.get("runId")
        != run_id
    ):
        _add(
            issues,
            "error",
            "REC203",
            filename,
            f"{filename}.runId does not "
            "match session.json",
        )

    if (
        require_plan_id
        and document.get(
            "planId"
        )
        != plan_id
    ):
        _add(
            issues,
            "error",
            "REC204",
            filename,
            f"{filename}.planId does not "
            "match session.json",
        )




def _read_events(
    directory: Path,
    *,
    run_id: str,
    issues: list[
        RunRecoveryIssue
    ],
) -> tuple[
    int,
    str | None,
    str | None,
]:
    """Read durable Run events and recover the last known execution state."""

    path = (
        directory
        / "events.jsonl"
    )

    if not path.exists():
        _add(
            issues,
            "warning",
            "REC104",
            "events.jsonl",
            "events.jsonl is missing",
        )
        return 0, None, None

    if not path.is_file():
        _add(
            issues,
            "error",
            "REC201",
            "events.jsonl",
            "events.jsonl exists but "
            "is not a regular file",
        )
        return 0, None, None

    count = 0
    previous_sequence: int | None = None

    latest_state: str | None = None
    latest_execution_id: str | None = None

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as stream:
            for line_number, line in enumerate(
                stream,
                start=1,
            ):
                location = (
                    "events.jsonl:"
                    f"{line_number}"
                )

                if not line.strip():
                    _add(
                        issues,
                        "error",
                        "REC301",
                        location,
                        "blank Event journal line",
                    )
                    continue

                try:
                    record = _load_json_line(
                        line,
                        path=path,
                        line_number=line_number,
                    )
                except ValueError as exc:
                    _add(
                        issues,
                        "error",
                        "REC302",
                        location,
                        str(exc),
                    )
                    continue

                count += 1

                if (
                    record.get("runId")
                    != run_id
                ):
                    _add(
                        issues,
                        "error",
                        "REC303",
                        location,
                        "Event belongs to "
                        "a different Run",
                    )

                sequence = record.get(
                    "sequence"
                )

                if (
                    not isinstance(
                        sequence,
                        int,
                    )
                    or isinstance(
                        sequence,
                        bool,
                    )
                    or sequence < 0
                ):
                    _add(
                        issues,
                        "error",
                        "REC304",
                        location,
                        "Event sequence must be "
                        "a non-negative integer",
                    )
                else:
                    if (
                        previous_sequence
                        is not None
                        and sequence
                        != previous_sequence + 1
                    ):
                        _add(
                            issues,
                            "error",
                            "REC305",
                            location,
                            "Event sequence is "
                            "not contiguous",
                        )

                    previous_sequence = (
                        sequence
                    )

                try:
                    _parse_timestamp(
                        record.get(
                            "recordedAt"
                        ),
                        field_name=(
                            "Event recordedAt"
                        ),
                    )
                except ValueError as exc:
                    _add(
                        issues,
                        "error",
                        "REC306",
                        location,
                        str(exc),
                    )

                event = record.get(
                    "event"
                )

                if not isinstance(
                    event,
                    dict,
                ):
                    _add(
                        issues,
                        "error",
                        "REC307",
                        location,
                        "Event envelope payload "
                        "must be an object",
                    )
                    continue

                raw_execution_id = (
                    event.get(
                        "executionId"
                    )
                )

                if (
                    isinstance(
                        raw_execution_id,
                        str,
                    )
                    and raw_execution_id.strip()
                ):
                    latest_execution_id = (
                        raw_execution_id.strip()
                    )

                # Canonical ExecutionEvent stores the exact execution snapshot
                # under status whenever the lifecycle event carries one.
                status_payload = (
                    event.get(
                        "status"
                    )
                )

                if isinstance(
                    status_payload,
                    dict,
                ):
                    status_execution_id = (
                        status_payload.get(
                            "executionId"
                        )
                    )

                    if (
                        isinstance(
                            status_execution_id,
                            str,
                        )
                        and status_execution_id.strip()
                    ):
                        latest_execution_id = (
                            status_execution_id.strip()
                        )

                    status_state = (
                        status_payload.get(
                            "state"
                        )
                    )

                    if (
                        isinstance(
                            status_state,
                            str,
                        )
                        and status_state
                        in _KNOWN_STATES
                    ):
                        latest_state = (
                            status_state
                        )
                        continue

                # Not every lifecycle event contains a complete status
                # snapshot. Recover the broad state from the event kind.
                event_name = event.get(
                    "event"
                )

                inferred_state = {
                    "prepared": "prepared",
                    "started": "running",
                    "stopping": "stopping",
                    "error": "failed",
                }.get(
                    event_name
                )

                if (
                    inferred_state
                    is not None
                ):
                    latest_state = (
                        inferred_state
                    )

    except UnicodeDecodeError as exc:
        _add(
            issues,
            "error",
            "REC302",
            "events.jsonl",
            (
                "events.jsonl is not "
                f"valid UTF-8: {exc}"
            ),
        )

    return (
        count,
        latest_state,
        latest_execution_id,
    )



def inspect_run_directory(
    directory: str | Path,
    *,
    assume_inactive: bool = False,
) -> RunRecoveryReport:
    """Inspect one Run directory without mutating it.

    ``assume_inactive`` must only be used when the caller already owns the
    recovery context and knows this Run has no live execution owner.
    """

    path = Path(
        directory
    ).expanduser().resolve()

    issues: list[
        RunRecoveryIssue
    ] = []

    if not path.exists():
        return RunRecoveryReport(
            directory=path,
            run_id=None,
            plan_id=None,
            classification=CORRUPTED,
            recovered_state=None,
            execution_id=None,
            event_count=0,
            final_record_present=False,
            temporary_files=(),
            issues=(
                RunRecoveryIssue(
                    severity="error",
                    code="REC001",
                    path=str(path),
                    message=(
                        "Run directory does "
                        "not exist"
                    ),
                ),
            ),
        )

    if not path.is_dir():
        return RunRecoveryReport(
            directory=path,
            run_id=None,
            plan_id=None,
            classification=CORRUPTED,
            recovered_state=None,
            execution_id=None,
            event_count=0,
            final_record_present=False,
            temporary_files=(),
            issues=(
                RunRecoveryIssue(
                    severity="error",
                    code="REC002",
                    path=str(path),
                    message=(
                        "Run path is not "
                        "a directory"
                    ),
                ),
            ),
        )

    session_path = (
        path
        / "session.json"
    )

    if not session_path.is_file():
        return RunRecoveryReport(
            directory=path,
            run_id=None,
            plan_id=None,
            classification=CORRUPTED,
            recovered_state=None,
            execution_id=None,
            event_count=0,
            final_record_present=False,
            temporary_files=tuple(
                sorted(
                    item.name
                    for item in path.glob(
                        ".*.tmp"
                    )
                )
            ),
            issues=(
                RunRecoveryIssue(
                    severity="error",
                    code="REC003",
                    path="session.json",
                    message=(
                        "session.json is "
                        "missing"
                    ),
                ),
            ),
        )

    try:
        session = _load_json(
            session_path
        )

        if (
            session.get("schema")
            != RUN_SESSION_SCHEMA
        ):
            raise ValueError(
                "session.schema is unsupported"
            )

        if (
            session.get("layout")
            != RUN_LAYOUT_SCHEMA
        ):
            raise ValueError(
                "session.layout is unsupported"
            )

        run_id = _text_field(
            session,
            "run_id",
            source="session",
        )

        plan_document = (
            session.get("plan")
        )

        if not isinstance(
            plan_document,
            dict,
        ):
            raise ValueError(
                "session.plan must be an object"
            )

        plan_id = _text_field(
            plan_document,
            "id",
            source="session.plan",
        )

        _text_field(
            plan_document,
            "kind",
            source="session.plan",
        )

        _parse_timestamp(
            session.get(
                "created_at"
            ),
            field_name=(
                "session.created_at"
            ),
        )

        operation_document = (
            session.get(
                "operation"
            )
        )

        if not isinstance(
            operation_document,
            dict,
        ):
            raise ValueError(
                "session.operation must be an object"
            )

        _text_field(
            operation_document,
            "kind",
            source="session.operation",
        )

        _text_field(
            operation_document,
            "subject",
            source="session.operation",
        )

        _text_field(
            operation_document,
            "subject_revision",
            source="session.operation",
        )
    except ValueError as exc:
        return RunRecoveryReport(
            directory=path,
            run_id=None,
            plan_id=None,
            classification=CORRUPTED,
            recovered_state=None,
            execution_id=None,
            event_count=0,
            final_record_present=False,
            temporary_files=(),
            issues=(
                RunRecoveryIssue(
                    severity="error",
                    code="REC004",
                    path="session.json",
                    message=str(exc),
                ),
            ),
        )

    if path.name != run_id:
        _add(
            issues,
            "error",
            "REC005",
            "session.json",
            "Run directory name does not "
            "match session.runId",
        )

    definition = _load_optional(
        path,
        "definition.json",
        missing_code="REC101",
        issues=issues,
    )

    plan = _load_optional(
        path,
        "plan.json",
        missing_code="REC102",
        issues=issues,
    )

    environment = _load_optional(
        path,
        "environment.json",
        missing_code="REC103",
        issues=issues,
    )

    status = _load_optional(
        path,
        "status.json",
        missing_code="REC105",
        issues=issues,
    )

    final_record_path = (
        path
        / "run.json"
    )

    final_record = (
        _load_optional(
            path,
            "run.json",
            missing_code="REC106",
            issues=issues,
        )
        if final_record_path.exists()
        else None
    )

    _check_identity(
        definition,
        filename="definition.json",
        run_id=run_id,
        plan_id=plan_id,
        issues=issues,
    )

    _check_identity(
        plan,
        filename="plan.json",
        run_id=run_id,
        plan_id=plan_id,
        issues=issues,
    )

    _check_identity(
        environment,
        filename="environment.json",
        run_id=run_id,
        plan_id=plan_id,
        issues=issues,
    )

    _check_identity(
        status,
        filename="status.json",
        run_id=run_id,
        plan_id=plan_id,
        issues=issues,
    )

    if (
        final_record is not None
        and final_record.get(
            "runId"
        )
        != run_id
    ):
        _add(
            issues,
            "error",
            "REC203",
            "run.json",
            "run.json belongs to "
            "a different Run",
        )

    # Definition revision must be exactly the revision pinned by the Plan.
    if (
        definition is not None
        and plan is not None
    ):
        definition_content = (
            definition.get(
                "content"
            )
        )

        plan_content = (
            plan.get(
                "content"
            )
        )

        if not isinstance(
            definition_content,
            dict,
        ):
            _add(
                issues,
                "error",
                "REC401",
                "definition.json",
                "Definition snapshot content "
                "must be an object",
            )

        if not isinstance(
            plan_content,
            dict,
        ):
            _add(
                issues,
                "error",
                "REC402",
                "plan.json",
                "Plan snapshot content "
                "must be an object",
            )

        if (
            isinstance(
                definition_content,
                dict,
            )
            and isinstance(
                plan_content,
                dict,
            )
        ):
            if (
                definition_content.get(
                    "revision"
                )
                != plan_content.get(
                    "subjectRevision"
                )
            ):
                _add(
                    issues,
                    "error",
                    "REC403",
                    "definition.json",
                    "Definition revision does "
                    "not match Plan subjectRevision",
                )

            if (
                plan_content.get(
                    "planId"
                )
                != plan_id
            ):
                _add(
                    issues,
                    "error",
                    "REC404",
                    "plan.json",
                    "Plan snapshot content.planId "
                    "does not match session.planId",
                )

    (
        event_count,
        event_state,
        event_execution_id,
    ) = _read_events(
        path,
        run_id=run_id,
        issues=issues,
    )

    status_state: str | None = None
    execution_id: str | None = None

    if status is not None:
        raw_state = status.get(
            "state"
        )

        if (
            not isinstance(
                raw_state,
                str,
            )
            or raw_state
            not in _KNOWN_STATES
        ):
            _add(
                issues,
                "error",
                "REC501",
                "status.json",
                "status.state is invalid",
            )
        else:
            status_state = (
                raw_state
            )

        raw_execution_id = (
            status.get(
                "executionId"
            )
        )

        if (
            raw_execution_id
            is not None
            and (
                not isinstance(
                    raw_execution_id,
                    str,
                )
                or not raw_execution_id.strip()
            )
        ):
            _add(
                issues,
                "error",
                "REC502",
                "status.json",
                "status.executionId must "
                "be null or a non-empty string",
            )
        elif isinstance(
            raw_execution_id,
            str,
        ):
            execution_id = (
                raw_execution_id
            )

        try:
            _parse_timestamp(
                status.get(
                    "updatedAt"
                ),
                field_name=(
                    "status.updatedAt"
                ),
            )
        except ValueError as exc:
            _add(
                issues,
                "error",
                "REC503",
                "status.json",
                str(exc),
            )

    final_state: str | None = None
    final_execution_id: str | None = None

    if final_record is not None:
        execution = (
            final_record.get(
                "execution"
            )
        )

        if not isinstance(
            execution,
            dict,
        ):
            _add(
                issues,
                "error",
                "REC601",
                "run.json",
                "run.json.execution must "
                "be an object",
            )
        else:
            raw_final_state = (
                execution.get(
                    "state"
                )
            )

            if (
                not isinstance(
                    raw_final_state,
                    str,
                )
                or raw_final_state
                not in _TERMINAL_STATES
            ):
                _add(
                    issues,
                    "error",
                    "REC602",
                    "run.json",
                    "final Execution state "
                    "must be terminal",
                )
            else:
                final_state = (
                    raw_final_state
                )

            if (
                execution.get(
                    "terminal"
                )
                is not True
            ):
                _add(
                    issues,
                    "error",
                    "REC603",
                    "run.json",
                    "final Execution must "
                    "declare terminal=true",
                )

            raw_id = execution.get(
                "executionId"
            )

            if (
                not isinstance(
                    raw_id,
                    str,
                )
                or not raw_id.strip()
            ):
                _add(
                    issues,
                    "error",
                    "REC604",
                    "run.json",
                    "final executionId must "
                    "be a non-empty string",
                )
            else:
                final_execution_id = (
                    raw_id
                )

            final_plan = (
                execution.get(
                    "plan"
                )
            )

            if (
                not isinstance(
                    final_plan,
                    dict,
                )
                or final_plan.get(
                    "planId"
                )
                != plan_id
            ):
                _add(
                    issues,
                    "error",
                    "REC605",
                    "run.json",
                    "final Execution planId "
                    "does not match session.planId",
                )

            started_at: datetime | None = None
            finished_at: datetime | None = None

            try:
                started_at = _parse_timestamp(
                    execution.get(
                        "startedAt"
                    ),
                    field_name=(
                        "run.execution.startedAt"
                    ),
                )
            except ValueError as exc:
                _add(
                    issues,
                    "error",
                    "REC606",
                    "run.json",
                    str(exc),
                )

            try:
                finished_at = _parse_timestamp(
                    execution.get(
                        "finishedAt"
                    ),
                    field_name=(
                        "run.execution.finishedAt"
                    ),
                )
            except ValueError as exc:
                _add(
                    issues,
                    "error",
                    "REC606",
                    "run.json",
                    str(exc),
                )

            if (
                started_at is not None
                and finished_at is not None
                and finished_at < started_at
            ):
                _add(
                    issues,
                    "error",
                    "REC610",
                    "run.json",
                    "run.execution.finishedAt "
                    "must not precede startedAt",
                )

    if (
        final_record is not None
        and status_state is not None
    ):
        if (
            status_state
            not in _TERMINAL_STATES
        ):
            _add(
                issues,
                "error",
                "REC607",
                "run.json",
                "final RunRecord exists while "
                "status is non-terminal",
            )

        if (
            final_state is not None
            and status_state
            != final_state
        ):
            _add(
                issues,
                "error",
                "REC608",
                "run.json",
                "final RunRecord state does "
                "not match status.state",
            )

    if (
        execution_id is not None
        and final_execution_id is not None
        and execution_id
        != final_execution_id
    ):
        _add(
            issues,
            "error",
            "REC609",
            "run.json",
            "final executionId does not "
            "match status.executionId",
        )

    # A terminal execution that actually started must have immutable run.json.
    if (
        final_record is None
        and status_state
        in _TERMINAL_STATES
        and execution_id is not None
    ):
        _add(
            issues,
            "warning",
            "REC106",
            "run.json",
            "terminal execution has no "
            "immutable final RunRecord",
        )

    temporary_files = tuple(
        sorted(
            str(
                item.relative_to(
                    path
                )
            )
            for item in path.glob(
                ".*.tmp"
            )
            if item.is_file()
        )
    )

    for temporary_file in (
        temporary_files
    ):
        _add(
            issues,
            "warning",
            "REC701",
            temporary_file,
            "stale temporary Run file "
            "was left after interrupted "
            "atomic publication",
        )

    has_errors = any(
        issue.severity == "error"
        for issue in issues
    )

    has_incomplete = any(
        issue.code
        in _INCOMPLETE_CODES
        for issue in issues
    )

    recovered_state = (
        final_state
        or status_state
        or event_state
    )

    if has_errors:
        classification: (
            RunRecoveryClassification
        ) = CORRUPTED
    elif final_record is not None:
        if has_incomplete:
            classification = INCOMPLETE
        else:
            classification = (
                HEALTHY_TERMINAL
            )
    elif (
        status_state == "failed"
        and execution_id is None
    ):
        if has_incomplete:
            classification = INCOMPLETE
        else:
            classification = (
                FAILED_BEFORE_START
            )
    elif (
        status_state is not None
        and status_state
        in _TERMINAL_STATES
    ):
        classification = INCOMPLETE
    elif (
        status_state is not None
        and assume_inactive
    ):
        classification = INTERRUPTED
    elif (
        status_state is not None
    ):
        if has_incomplete:
            classification = INCOMPLETE
        else:
            classification = (
                ACTIVE_OR_UNKNOWN
            )
    else:
        classification = INCOMPLETE

    return RunRecoveryReport(
        directory=path,
        run_id=run_id,
        plan_id=plan_id,
        classification=classification,
        recovered_state=(
            recovered_state
        ),
        execution_id=(
            final_execution_id
            or execution_id
            or event_execution_id
        ),
        event_count=event_count,
        final_record_present=(
            final_record is not None
        ),
        temporary_files=(
            temporary_files
        ),
        issues=tuple(
            issues
        ),
    )


__all__ = [
    "ACTIVE_OR_UNKNOWN",
    "CORRUPTED",
    "FAILED_BEFORE_START",
    "HEALTHY_TERMINAL",
    "INCOMPLETE",
    "INTERRUPTED",
    "RunRecoveryClassification",
    "RunRecoveryIssue",
    "RunRecoveryReport",
    "inspect_run_directory",
]
