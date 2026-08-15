from datetime import datetime, timedelta, timezone

import pytest

from nodrix.model import (
    CONSUMES,
    PRODUCES,
    ArtifactRecord,
    DatasetRecord,
    EntityRef,
    ExecutionRecord,
    Operation,
    PlanRecord,
    RecordRef,
    RevisionRef,
    combine_provenance,
    record_run,
    run_io_relations,
    run_lifecycle_relations,
    run_ref,
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


def dataset_record(
    *,
    name: str = "livox-session",
    digest: str = "b" * 64,
) -> DatasetRecord:
    entity = EntityRef(
        kind="dataset",
        namespace="project",
        name=name,
    )

    return DatasetRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            digest,
        ),
        kind="recording",
        uri=f"datasets/{name}.ndrx",
    )


def artifact_record(
    *,
    name: str = "global-map",
    digest: str = "c" * 64,
) -> ArtifactRecord:
    entity = EntityRef(
        kind="artifact",
        namespace="project",
        name=name,
    )

    return ArtifactRecord(
        entity=entity,
        revision=RevisionRef.from_sha256(
            entity,
            digest,
        ),
        kind="mapping.point-cloud",
        uri=f"artifacts/{name}.ply",
    )


def test_run_ref_uses_run_identity() -> None:
    run = finished_run()

    assert run_ref(run) == RecordRef(
        kind="run",
        record_id="run-001",
    )


def test_run_consumes_dataset_revision() -> None:
    run = finished_run()
    dataset = dataset_record()

    graph = run_io_relations(
        run,
        inputs=(dataset,),
    )

    assert len(graph.relations) == 1

    relation = graph.relations[0]

    assert relation.source == run_ref(run)
    assert relation.kind == CONSUMES
    assert relation.target == dataset.revision


def test_run_produces_artifact_revision() -> None:
    run = finished_run()
    artifact = artifact_record()

    graph = run_io_relations(
        run,
        outputs=(artifact,),
    )

    relation = graph.relations[0]

    assert relation.source == run_ref(run)
    assert relation.kind == PRODUCES
    assert relation.target == artifact.revision


def test_run_can_consume_artifact() -> None:
    run = finished_run()
    previous_map = artifact_record(
        name="previous-map",
    )

    graph = run_io_relations(
        run,
        inputs=(previous_map,),
    )

    assert graph.relations[0].kind == CONSUMES
    assert (
        graph.relations[0].target
        == previous_map.revision
    )


def test_run_can_produce_dataset() -> None:
    run = finished_run()
    derived = dataset_record(
        name="filtered-cloud",
    )

    graph = run_io_relations(
        run,
        outputs=(derived,),
    )

    assert graph.relations[0].kind == PRODUCES
    assert (
        graph.relations[0].target
        == derived.revision
    )


def test_raw_revision_supports_future_custom_record_types() -> None:
    run = finished_run()

    entity = EntityRef(
        kind="robot-map",
        namespace="user",
        name="semantic-world",
    )

    revision = RevisionRef.from_sha256(
        entity,
        "d" * 64,
    )

    graph = run_io_relations(
        run,
        outputs=(revision,),
    )

    assert graph.relations[0].target == revision
    assert graph.relations[0].kind == PRODUCES


def test_duplicate_input_revision_is_emitted_once() -> None:
    run = finished_run()
    dataset = dataset_record()

    graph = run_io_relations(
        run,
        inputs=(
            dataset,
            dataset.revision,
            dataset,
        ),
    )

    assert len(graph.relations) == 1


def test_input_and_output_can_reference_same_revision() -> None:
    run = finished_run()
    artifact = artifact_record()

    graph = run_io_relations(
        run,
        inputs=(artifact,),
        outputs=(artifact,),
    )

    assert len(graph.relations) == 2

    assert graph.relations[0].kind == CONSUMES
    assert graph.relations[1].kind == PRODUCES

    assert (
        graph.relations[0].target
        == graph.relations[1].target
    )


def test_invalid_provenance_item_is_rejected() -> None:
    run = finished_run()

    with pytest.raises(
        TypeError,
        match="provenance item",
    ):
        run_io_relations(
            run,
            inputs=(
                object(),  # type: ignore[arg-type]
            ),
        )


def test_combine_provenance_preserves_graph_order() -> None:
    run = finished_run()
    dataset = dataset_record()
    artifact = artifact_record()

    lifecycle = run_lifecycle_relations(
        run
    )

    io = run_io_relations(
        run,
        inputs=(dataset,),
        outputs=(artifact,),
    )

    graph = combine_provenance(
        lifecycle,
        io,
    )

    assert len(graph.relations) == 4

    assert (
        graph.relations[:2]
        == lifecycle.relations
    )

    assert (
        graph.relations[2:]
        == io.relations
    )


def test_complete_provenance_graph_is_queryable() -> None:
    run = finished_run()
    dataset = dataset_record()
    artifact = artifact_record()

    graph = combine_provenance(
        run_lifecycle_relations(run),
        run_io_relations(
            run,
            inputs=(dataset,),
            outputs=(artifact,),
        ),
    )

    canonical_run = run_ref(run)

    consumed = graph.outgoing(
        canonical_run,
        kind=CONSUMES,
    )

    produced = graph.outgoing(
        canonical_run,
        kind=PRODUCES,
    )

    assert len(consumed) == 1
    assert consumed[0].target == dataset.revision

    assert len(produced) == 1
    assert produced[0].target == artifact.revision
