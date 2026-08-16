from dataclasses import FrozenInstanceError

import pytest

from nodrix.model import (
    BENCHMARK,
    BUILD,
    RUN,
    EntityRef,
    Operation,
    OperationKind,
    RevisionRef,
)


def mapping_system() -> EntityRef:
    return EntityRef(
        kind="system",
        namespace="project",
        name="mapping",
    )


def test_operation_kind_normalizes_value() -> None:
    kind = OperationKind("  RUN  ")

    assert kind.value == "run"
    assert str(kind) == "run"


def test_operation_kind_supports_extension_names() -> None:
    kind = OperationKind("mapping.reconstruct")

    assert str(kind) == "mapping.reconstruct"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "bad kind",
        "1run",
        "run!",
        "run/system",
    ],
)
def test_operation_kind_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        OperationKind(value)


def test_builtin_operation_kinds_are_canonical() -> None:
    assert str(BUILD) == "build"
    assert str(RUN) == "run"
    assert str(BENCHMARK) == "benchmark"


def test_operation_targets_logical_entity() -> None:
    system = mapping_system()

    operation = Operation(
        kind=RUN,
        subject=system,
    )

    assert operation.kind == RUN
    assert operation.kind_name == "run"
    assert operation.subject == system
    assert operation.subject_revision is None
    assert dict(operation.parameters) == {}


def test_operation_accepts_string_kind() -> None:
    operation = Operation(
        kind="BENCHMARK",
        subject=mapping_system(),
    )

    assert operation.kind == BENCHMARK
    assert operation.kind_name == "benchmark"


def test_operation_can_pin_subject_revision() -> None:
    system = mapping_system()
    revision = RevisionRef.from_sha256(
        system,
        "a" * 64,
    )

    operation = Operation(
        kind="run",
        subject=system,
        subject_revision=revision,
    )

    assert operation.subject_revision == revision


def test_operation_rejects_revision_of_another_entity() -> None:
    system = mapping_system()

    other = EntityRef(
        kind="system",
        namespace="project",
        name="perception",
    )
    revision = RevisionRef.from_sha256(
        other,
        "a" * 64,
    )

    with pytest.raises(
        ValueError,
        match="must reference the operation subject",
    ):
        Operation(
            kind="run",
            subject=system,
            subject_revision=revision,
        )


def test_operation_parameters_are_copied_and_read_only() -> None:
    source = {
        "repeat": 3,
        "profile": "release",
    }

    operation = Operation(
        kind="benchmark",
        subject=mapping_system(),
        parameters=source,
    )

    source["repeat"] = 99

    assert operation.parameters["repeat"] == 3

    with pytest.raises(TypeError):
        operation.parameters["repeat"] = 5  # type: ignore[index]


def test_operation_is_immutable() -> None:
    operation = Operation(
        kind="run",
        subject=mapping_system(),
    )

    with pytest.raises(FrozenInstanceError):
        operation.subject = EntityRef(  # type: ignore[misc]
            kind="system",
            namespace="project",
            name="other",
        )


def test_same_entity_can_be_subject_of_different_operations() -> None:
    system = mapping_system()

    run = Operation(
        kind="run",
        subject=system,
    )
    benchmark = Operation(
        kind="benchmark",
        subject=system,
        parameters={"repeat": 3},
    )

    assert run.subject == benchmark.subject
    assert run.kind != benchmark.kind


def test_prepare_is_canonical_builtin_operation_kind() -> None:
    from nodrix.model import PREPARE

    assert PREPARE == OperationKind("prepare")
    assert PREPARE.value == "prepare"
