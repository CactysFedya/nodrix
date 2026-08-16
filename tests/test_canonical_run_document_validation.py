from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from nodrix.model import (
    EntityRef,
    ExecutionRecord,
    Operation,
    PlanRecord,
    RevisionRef,
    record_run,
    run_lifecycle_relations,
)
from nodrix.run_document import (
    run_to_document,
    write_run_document,
)
from nodrix.run_document_validation import (
    RunDocumentValidationError,
    load_canonical_run,
    loads_run_document,
    read_run_document,
    validate_run_document,
)


def finished_run():
    system = EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )

    plan = PlanRecord(
        plan_id="plan-001",
        kind="system-execution",
        operation=Operation(
            kind="run",
            subject=system,
        ),
        subject_revision=RevisionRef.from_sha256(
            system,
            "a" * 64,
        ),
        payload={},
    )

    started = datetime(
        2026,
        8,
        15,
        20,
        0,
        tzinfo=timezone.utc,
    )

    execution = ExecutionRecord(
        execution_id="execution-001",
        plan=plan,
        executor="nodrix.system.orchestrator",
        state="completed",
        started_at=started,
        finished_at=(
            started + timedelta(seconds=30)
        ),
    )

    return record_run(
        execution,
        run_id="run-001",
    )


def valid_document():
    run = finished_run()

    return run_to_document(
        run,
        provenance=run_lifecycle_relations(
            run
        ),
    )


def test_validate_run_document_returns_semantic_view() -> None:
    validated = validate_run_document(
        valid_document()
    )

    assert validated.run_id == "run-001"

    assert str(validated.run_ref) == (
        "nodrix://record/run/run-001"
    )

    assert str(validated.subject) == (
        "nodrix://system/project/mapping"
    )

    assert validated.operation_kind.value == "run"
    assert validated.plan_kind.value == "system-execution"

    assert validated.state.value == "completed"
    assert validated.successful
    assert validated.duration_seconds == 30.0

    assert len(validated.relations.relations) == 2


def test_loads_run_document_round_trip() -> None:
    text = json.dumps(
        valid_document()
    )

    validated = loads_run_document(
        text
    )

    assert validated.run_id == "run-001"
    assert validated.execution_ref.record_id == (
        "execution-001"
    )


def test_reader_loads_written_run_document(
    tmp_path,
) -> None:
    run = finished_run()

    path = write_run_document(
        run,
        project=tmp_path,
        provenance=run_lifecycle_relations(
            run
        ),
    )

    validated = read_run_document(
        path
    )

    assert validated.run_id == run.run_id
    assert validated.subject == run.subject
    assert validated.subject_revision == (
        run.subject_revision
    )


def test_load_canonical_run_uses_exact_storage_path(
    tmp_path,
) -> None:
    run = finished_run()

    write_run_document(
        run,
        project=tmp_path,
        provenance=run_lifecycle_relations(
            run
        ),
    )

    validated = load_canonical_run(
        "run-001",
        project=tmp_path,
    )

    assert validated.run_id == "run-001"


def test_wrong_schema_is_rejected() -> None:
    document = valid_document()
    document["schema"] = "nodrix.run/v99"

    with pytest.raises(
        RunDocumentValidationError,
        match="schema",
    ):
        validate_run_document(
            document
        )


def test_wrong_kind_is_rejected() -> None:
    document = valid_document()
    document["kind"] = "Dataset"

    with pytest.raises(
        RunDocumentValidationError,
        match="kind",
    ):
        validate_run_document(
            document
        )


def test_run_ref_must_match_run_id() -> None:
    document = valid_document()
    document["ref"] = (
        "nodrix://record/run/run-other"
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="ref",
    ):
        validate_run_document(
            document
        )


def test_subject_revision_must_match_entity() -> None:
    document = valid_document()

    document["subject"]["revision"] = (
        "nodrix://system/project/perception"
        "@sha256:"
        + "b" * 64
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="subject.revision",
    ):
        validate_run_document(
            document
        )


def test_execution_ref_must_match_execution_id() -> None:
    document = valid_document()

    document["execution"]["ref"] = (
        "nodrix://record/execution/"
        "execution-other"
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="execution.ref",
    ):
        validate_run_document(
            document
        )


def test_execution_state_must_match_status() -> None:
    document = valid_document()

    document["execution"]["state"] = "failed"

    with pytest.raises(
        RunDocumentValidationError,
        match="execution.state",
    ):
        validate_run_document(
            document
        )


def test_run_document_requires_terminal_state() -> None:
    document = valid_document()

    document["status"] = "running"
    document["execution"]["state"] = "running"
    document["successful"] = False

    with pytest.raises(
        RunDocumentValidationError,
        match="terminal",
    ):
        validate_run_document(
            document
        )


def test_successful_must_match_state() -> None:
    document = valid_document()

    document["successful"] = False

    with pytest.raises(
        RunDocumentValidationError,
        match="successful",
    ):
        validate_run_document(
            document
        )


def test_duration_must_match_timestamps() -> None:
    document = valid_document()

    document["duration_seconds"] = 99.0

    with pytest.raises(
        RunDocumentValidationError,
        match="duration_seconds",
    ):
        validate_run_document(
            document
        )


def test_naive_timestamp_is_rejected() -> None:
    document = valid_document()

    document["execution"]["started_at"] = (
        "2026-08-15T20:00:00"
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="timezone-aware",
    ):
        validate_run_document(
            document
        )


def test_invalid_relation_reference_is_rejected() -> None:
    document = valid_document()

    document["relations"][0]["target"] = (
        "not-a-reference"
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="relations\\[0\\].target",
    ):
        validate_run_document(
            document
        )


def test_wrong_lifecycle_execution_target_is_rejected() -> None:
    document = valid_document()

    document["relations"][0]["target"] = (
        "nodrix://record/execution/"
        "execution-other"
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="executed_as",
    ):
        validate_run_document(
            document
        )


def test_wrong_lifecycle_run_target_is_rejected() -> None:
    document = valid_document()

    document["relations"][1]["target"] = (
        "nodrix://record/run/run-other"
    )

    with pytest.raises(
        RunDocumentValidationError,
        match="recorded_as",
    ):
        validate_run_document(
            document
        )


def test_document_copy_can_be_validated_independently() -> None:
    original = valid_document()
    copied = deepcopy(original)

    validated = validate_run_document(
        copied
    )

    assert validated.run_id == "run-001"
    assert copied == original


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(
        RunDocumentValidationError,
        match="invalid JSON",
    ):
        loads_run_document(
            "{broken"
        )


def test_non_object_json_root_is_rejected() -> None:
    with pytest.raises(
        RunDocumentValidationError,
        match="root must be an object",
    ):
        loads_run_document(
            "[]"
        )


def test_unsafe_requested_run_id_is_rejected(
    tmp_path,
) -> None:
    with pytest.raises(
        RunDocumentValidationError,
        match="run_id",
    ):
        load_canonical_run(
            "../outside",
            project=tmp_path,
        )
