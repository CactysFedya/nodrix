from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from nodrix.foreground_operation import (
    persist_foreground_execution,
)
from nodrix.model import (
    ArtifactRecord,
    BENCHMARK,
    BENCHMARK_PLAN,
    EntityRef,
    ExecutionRecord,
    ExecutionState,
    Operation,
    PlanRecord,
    RevisionRef,
)
from nodrix.model.relations import (
    PRODUCES,
)


STARTED = datetime(
    2026,
    8,
    20,
    18,
    0,
    tzinfo=timezone.utc,
)


def _plan() -> PlanRecord:
    subject = EntityRef(
        kind="pipeline",
        namespace="project",
        name="foreground-output-test",
    )

    revision = (
        RevisionRef.from_sha256(
            subject,
            "a" * 64,
        )
    )

    operation = Operation(
        kind=BENCHMARK,
        subject=subject,
        subject_revision=revision,
        parameters={},
    )

    return PlanRecord(
        plan_id="plan_foreground-output",
        kind=BENCHMARK_PLAN,
        operation=operation,
        subject_revision=revision,
        payload={
            "test": True,
        },
    )


def _artifact() -> ArtifactRecord:
    entity = EntityRef(
        kind="artifact",
        namespace="project",
        name="benchmark-result",
    )

    revision = (
        RevisionRef.from_sha256(
            entity,
            "b" * 64,
        )
    )

    return ArtifactRecord(
        entity=entity,
        revision=revision,
        kind="benchmark.result",
        uri=(
            "file:///tmp/"
            "benchmark-result.json"
        ),
        media_type=(
            "application/vnd.nodrix."
            "benchmark-result+json"
        ),
        size_bytes=123,
        metadata={
            "test": True,
        },
    )


def test_foreground_execution_persists_produced_artifact_revision(
    tmp_path,
) -> None:
    plan = _plan()

    execution = ExecutionRecord(
        execution_id=(
            "execution-foreground-output"
        ),
        plan=plan,
        executor="nodrix.test",
        state=ExecutionState.COMPLETED,
        started_at=STARTED,
        finished_at=(
            STARTED
            + timedelta(
                seconds=1
            )
        ),
    )

    artifact = _artifact()

    outcome = (
        persist_foreground_execution(
            plan,
            execution,
            project=tmp_path,
            outputs=(
                artifact,
            ),
        )
    )

    relations = tuple(
        outcome.history
        .provenance
        .relations
    )

    produced = tuple(
        relation
        for relation
        in relations
        if (
            relation.kind
            == PRODUCES
        )
    )

    assert len(
        produced
    ) == 1

    assert (
        produced[
            0
        ].target
        == artifact.revision
    )

    assert (
        produced[
            0
        ].source.record_id
        == outcome.history.run.run_id
    )
