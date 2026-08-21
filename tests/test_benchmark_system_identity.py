from __future__ import annotations

from pathlib import Path

import pytest

from nodrix.benchmark_system_identity import (
    canonical_benchmark_workload_set,
    canonical_system_benchmark_operation,
    canonical_system_benchmark_plan_record,
)
from nodrix.benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from nodrix.model import (
    BENCHMARK,
    BENCHMARK_PLAN,
)
from nodrix.system import (
    SystemModel,
    plan_system,
)
from nodrix.system.canonical import (
    system_plan_record,
)


def _source(
    tmp_path: Path,
) -> Path:
    path = (
        tmp_path
        / "system.yaml"
    )

    path.write_text(
        "canonical System source\n",
        encoding="utf-8",
    )

    return path


def _system_plan(
    *,
    marker: str = "a",
):
    system = SystemModel(
        name="mapping",
        metadata={
            "marker": marker,
        },
    )

    return system_plan_record(
        plan_system(
            system
        )
    )


def _benchmark(
    tmp_path: Path,
    *,
    repeat: int = 3,
    warmup: int = 1,
    profile: str | None = None,
    set_values: tuple[str, ...] = (),
    block_values: tuple[str, ...] = (),
) -> BenchmarkPlan:
    return BenchmarkPlan(
        pipeline=_source(
            tmp_path
        ),
        repeat=repeat,
        warmup=warmup,
        variants=(
            BenchmarkVariant(
                "default",
                profile=profile,
                set_values=set_values,
                block_values=block_values,
            ),
        ),
    )


def test_workload_set_is_a_benchmark_not_pipeline_or_system(
    tmp_path,
) -> None:
    plan = _benchmark(
        tmp_path
    )

    system_plan = (
        _system_plan()
    )

    workload_set = (
        canonical_benchmark_workload_set(
            plan,
            variant_plans={
                "default": (
                    system_plan
                ),
            },
        )
    )

    assert (
        workload_set.entity.kind
        == "benchmark"
    )

    assert (
        workload_set.system.kind
        == "system"
    )

    assert (
        workload_set.entity.name
        == "mapping-benchmark"
    )

    assert (
        workload_set.revision.entity
        == workload_set.entity
    )

    assert (
        workload_set.variants[
            0
        ].system_revision
        == system_plan.subject_revision
    )

    assert (
        workload_set.variants[
            0
        ].system_plan_id
        == system_plan.plan_id
    )


def test_repeat_and_warmup_do_not_change_workload_revision(
    tmp_path,
) -> None:
    system_plan = (
        _system_plan()
    )

    first = (
        canonical_benchmark_workload_set(
            _benchmark(
                tmp_path,
                repeat=1,
                warmup=0,
            ),
            variant_plans={
                "default": (
                    system_plan
                ),
            },
        )
    )

    second = (
        canonical_benchmark_workload_set(
            _benchmark(
                tmp_path,
                repeat=20,
                warmup=10,
            ),
            variant_plans={
                "default": (
                    system_plan
                ),
            },
        )
    )

    assert (
        first.revision
        == second.revision
    )


def test_raw_profile_name_is_not_resolved_workload_identity(
    tmp_path,
) -> None:
    system_plan = (
        _system_plan()
    )

    first = (
        canonical_benchmark_workload_set(
            _benchmark(
                tmp_path,
                profile="field-a",
            ),
            variant_plans={
                "default": (
                    system_plan
                ),
            },
        )
    )

    second = (
        canonical_benchmark_workload_set(
            _benchmark(
                tmp_path,
                profile="field-b",
            ),
            variant_plans={
                "default": (
                    system_plan
                ),
            },
        )
    )

    # If two authoring profiles resolve to exactly the same System Definition
    # and Plan, they are the same measured workload semantics.
    assert (
        first.revision
        == second.revision
    )


def test_resolved_system_change_changes_workload_revision(
    tmp_path,
) -> None:
    plan = _benchmark(
        tmp_path
    )

    first = (
        canonical_benchmark_workload_set(
            plan,
            variant_plans={
                "default": (
                    _system_plan(
                        marker="a"
                    )
                ),
            },
        )
    )

    second = (
        canonical_benchmark_workload_set(
            plan,
            variant_plans={
                "default": (
                    _system_plan(
                        marker="b"
                    )
                ),
            },
        )
    )

    assert (
        first.revision
        != second.revision
    )


@pytest.mark.parametrize(
    (
        "set_values",
        "block_values",
    ),
    (
        (
            (
                "x=1",
            ),
            (),
        ),
        (
            (),
            (
                "detector=legacy.yaml",
            ),
        ),
    ),
)
def test_legacy_mutations_are_not_canonical_workload_identity(
    tmp_path,
    set_values,
    block_values,
) -> None:
    plan = _benchmark(
        tmp_path,
        set_values=set_values,
        block_values=block_values,
    )

    with pytest.raises(
        ValueError,
        match=(
            "legacy set/block"
        ),
    ):
        canonical_benchmark_workload_set(
            plan,
            variant_plans={
                "default": (
                    _system_plan()
                ),
            },
        )


def test_variant_plans_must_match_exact_variant_set(
    tmp_path,
) -> None:
    plan = BenchmarkPlan(
        pipeline=_source(
            tmp_path
        ),
        variants=(
            BenchmarkVariant(
                "a"
            ),
            BenchmarkVariant(
                "b"
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "match BenchmarkPlan variants exactly"
        ),
    ):
        canonical_benchmark_workload_set(
            plan,
            variant_plans={
                "a": (
                    _system_plan()
                ),
            },
        )


def test_canonical_operation_targets_workload_set_revision(
    tmp_path,
) -> None:
    plan = _benchmark(
        tmp_path,
        repeat=7,
        warmup=2,
        profile="field",
    )

    system_plan = (
        _system_plan()
    )

    workload_set = (
        canonical_benchmark_workload_set(
            plan,
            variant_plans={
                "default": (
                    system_plan
                ),
            },
        )
    )

    operation = (
        canonical_system_benchmark_operation(
            plan,
            workload_set=workload_set,
        )
    )

    assert (
        operation.kind
        == BENCHMARK
    )

    assert (
        operation.subject
        == workload_set.entity
    )

    assert (
        operation.subject_revision
        == workload_set.revision
    )

    assert (
        operation.parameters[
            "repeat"
        ]
        == 7
    )

    assert (
        operation.parameters[
            "warmup"
        ]
        == 2
    )

    variant = (
        operation.parameters[
            "variants"
        ][
            0
        ]
    )

    assert set(
        variant
    ) == {
        "name",
        "systemRevision",
        "systemPlanId",
    }

    assert (
        "profile"
        not in variant
    )

    assert (
        "set"
        not in variant
    )

    assert (
        "block"
        not in variant
    )


def test_execution_controls_change_plan_not_workload_identity(
    tmp_path,
) -> None:
    system_plan = (
        _system_plan()
    )

    first_domain = _benchmark(
        tmp_path,
        repeat=1,
        warmup=0,
    )

    second_domain = _benchmark(
        tmp_path,
        repeat=5,
        warmup=3,
    )

    workload_set = (
        canonical_benchmark_workload_set(
            first_domain,
            variant_plans={
                "default": (
                    system_plan
                ),
            },
        )
    )

    second_workload_set = (
        canonical_benchmark_workload_set(
            second_domain,
            variant_plans={
                "default": (
                    system_plan
                ),
            },
        )
    )

    assert (
        workload_set.revision
        == second_workload_set.revision
    )

    first_plan = (
        canonical_system_benchmark_plan_record(
            first_domain,
            workload_set=workload_set,
        )
    )

    second_plan = (
        canonical_system_benchmark_plan_record(
            second_domain,
            workload_set=(
                second_workload_set
            ),
        )
    )

    assert (
        first_plan.kind
        == BENCHMARK_PLAN
    )

    assert (
        first_plan.payload
        is first_domain
    )

    assert (
        first_plan.subject_revision
        == workload_set.revision
    )

    assert (
        first_plan.plan_id
        != second_plan.plan_id
    )


def test_explicit_benchmark_name_changes_entity_not_workload_digest(
    tmp_path,
) -> None:
    plan = _benchmark(
        tmp_path
    )

    system_plan = (
        _system_plan()
    )

    first = (
        canonical_benchmark_workload_set(
            plan,
            variant_plans={
                "default": (
                    system_plan
                ),
            },
            name="latency",
        )
    )

    second = (
        canonical_benchmark_workload_set(
            plan,
            variant_plans={
                "default": (
                    system_plan
                ),
            },
            name="throughput",
        )
    )

    assert (
        first.entity
        != second.entity
    )

    assert (
        first.revision.digest
        == second.revision.digest
    )
