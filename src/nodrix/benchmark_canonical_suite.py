"""Strict canonical Benchmark suite assembly.

This module assembles Benchmark Results from already persisted ordinary
canonical Runs.

It deliberately does not execute legacy Pipeline runtimes, read legacy report
dictionaries, interpret ``report["run_dir"]`` or call ``aggregate_reports``.

Execution of the measured Runs belongs to a separate executor boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .benchmark_result import (
    CanonicalBenchmarkResult,
    create_canonical_benchmark_result,
)
from .benchmark_result_artifact import (
    materialize_benchmark_result,
)
from .benchmark_runs import (
    CanonicalBenchmarkAggregation,
    aggregate_measured_canonical_benchmark_runs,
)
from .benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from .model import (
    ArtifactRecord,
    BENCHMARK_PLAN,
    PlanRecord,
)
from .run_bundle import (
    CanonicalRunBundle,
)


class CanonicalBenchmarkSuiteError(
    RuntimeError
):
    """Base error for strict canonical Benchmark suite assembly."""


class CanonicalBenchmarkSuiteInputError(
    CanonicalBenchmarkSuiteError
):
    """Measured canonical Run sets do not match the Benchmark Plan."""


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalBenchmarkVariantResult:
    """One Benchmark variant and its immutable canonical result evidence."""

    variant: BenchmarkVariant
    aggregation: CanonicalBenchmarkAggregation
    result: CanonicalBenchmarkResult
    artifact: ArtifactRecord

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.variant,
            BenchmarkVariant,
        ):
            raise TypeError(
                "variant must be a BenchmarkVariant"
            )

        if not isinstance(
            self.aggregation,
            CanonicalBenchmarkAggregation,
        ):
            raise TypeError(
                "aggregation must be "
                "CanonicalBenchmarkAggregation"
            )

        if not isinstance(
            self.result,
            CanonicalBenchmarkResult,
        ):
            raise TypeError(
                "result must be a "
                "CanonicalBenchmarkResult"
            )

        if not isinstance(
            self.artifact,
            ArtifactRecord,
        ):
            raise TypeError(
                "artifact must be an ArtifactRecord"
            )

        if (
            self.result.aggregation
            != self.aggregation
        ):
            raise ValueError(
                "result aggregation does not match "
                "variant aggregation"
            )

        if (
            self.result.variant.name
            != self.variant.name
        ):
            raise ValueError(
                "result variant does not match "
                "Benchmark variant"
            )

    @property
    def run_ids(
        self,
    ) -> tuple[str, ...]:
        return (
            self.aggregation
            .aggregate
            .run_ids
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "variant": (
                self.variant.name
            ),
            "measuredRuns": list(
                self.run_ids
            ),
            "resultIdentity": (
                self.result.identity.value
            ),
            "artifact": {
                "entity": str(
                    self.artifact.entity
                ),
                "revision": str(
                    self.artifact.revision
                ),
                "kind": (
                    self.artifact.kind
                ),
                "uri": (
                    self.artifact.uri
                ),
            },
        }


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalBenchmarkSuite:
    """In-memory canonical assembly result for one Benchmark Plan."""

    benchmark_plan_id: str
    variants: tuple[
        CanonicalBenchmarkVariantResult,
        ...,
    ]

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.benchmark_plan_id,
            str,
        ):
            raise TypeError(
                "benchmark_plan_id must be a string"
            )

        if not self.benchmark_plan_id.strip():
            raise ValueError(
                "benchmark_plan_id must be non-empty"
            )

        if not isinstance(
            self.variants,
            tuple,
        ):
            raise TypeError(
                "variants must be a tuple"
            )

        names: list[str] = []

        for item in self.variants:
            if not isinstance(
                item,
                CanonicalBenchmarkVariantResult,
            ):
                raise TypeError(
                    "variants must contain "
                    "CanonicalBenchmarkVariantResult values"
                )

            names.append(
                item.variant.name
            )

        if len(
            names
        ) != len(
            set(names)
        ):
            raise ValueError(
                "canonical Benchmark variant names "
                "must be unique"
            )

    @property
    def artifacts(
        self,
    ) -> tuple[
        ArtifactRecord,
        ...,
    ]:
        return tuple(
            item.artifact
            for item
            in self.variants
        )

    @property
    def result_identities(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            item.result.identity.value
            for item
            in self.variants
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "benchmarkPlanId": (
                self.benchmark_plan_id
            ),
            "variants": [
                item.to_dict()
                for item
                in self.variants
            ],
        }


def _benchmark_domain_plan(
    plan: PlanRecord,
) -> BenchmarkPlan:
    if not isinstance(
        plan,
        PlanRecord,
    ):
        raise TypeError(
            "plan must be a PlanRecord"
        )

    if (
        plan.kind
        != BENCHMARK_PLAN
    ):
        raise ValueError(
            "canonical Benchmark suite requires "
            "a BENCHMARK_PLAN PlanRecord"
        )

    domain_plan = (
        plan.payload
    )

    if not isinstance(
        domain_plan,
        BenchmarkPlan,
    ):
        raise TypeError(
            "Benchmark PlanRecord payload must "
            "be a BenchmarkPlan"
        )

    return domain_plan


def _validated_run_sets(
    domain_plan: BenchmarkPlan,
    measured_runs: Mapping[
        str,
        tuple[
            CanonicalRunBundle,
            ...,
        ],
    ],
) -> dict[
    str,
    tuple[
        CanonicalRunBundle,
        ...,
    ],
]:
    if not isinstance(
        measured_runs,
        Mapping,
    ):
        raise TypeError(
            "measured_runs must be a mapping"
        )

    expected = tuple(
        variant.name
        for variant
        in domain_plan.variants
    )

    expected_set = set(
        expected
    )

    actual_set = set(
        measured_runs
    )

    if (
        actual_set
        != expected_set
    ):
        missing = sorted(
            expected_set
            - actual_set
        )

        extra = sorted(
            actual_set
            - expected_set
        )

        raise CanonicalBenchmarkSuiteInputError(
            "measured canonical Run sets do not "
            "match Benchmark variants; "
            f"missing={missing}, extra={extra}"
        )

    result: dict[
        str,
        tuple[
            CanonicalRunBundle,
            ...,
        ],
    ] = {}

    all_run_ids: set[
        str
    ] = set()

    for variant_name in expected:
        bundles = (
            measured_runs[
                variant_name
            ]
        )

        if not isinstance(
            bundles,
            tuple,
        ):
            raise TypeError(
                "each measured Run set must be a tuple"
            )

        if not bundles:
            raise CanonicalBenchmarkSuiteInputError(
                "Benchmark variant "
                f"{variant_name!r} has no measured canonical Runs"
            )

        for bundle in bundles:
            if not isinstance(
                bundle,
                CanonicalRunBundle,
            ):
                raise TypeError(
                    "measured Run sets must contain "
                    "CanonicalRunBundle values"
                )

            run_id = (
                bundle.session.run_id
            )

            if (
                run_id
                in all_run_ids
            ):
                raise CanonicalBenchmarkSuiteInputError(
                    "canonical measured Run cannot belong "
                    "to multiple Benchmark variant sets: "
                    f"{run_id}"
                )

            all_run_ids.add(
                run_id
            )

        result[
            variant_name
        ] = bundles

    return result


def assemble_canonical_benchmark_suite(
    plan: PlanRecord,
    *,
    measured_runs: Mapping[
        str,
        tuple[
            CanonicalRunBundle,
            ...,
        ],
    ],
    project: str | Path = ".",
) -> CanonicalBenchmarkSuite:
    """Build canonical Benchmark Results from exact persisted measured Runs."""

    domain_plan = (
        _benchmark_domain_plan(
            plan
        )
    )

    run_sets = (
        _validated_run_sets(
            domain_plan,
            measured_runs,
        )
    )

    project_root = (
        Path(
            project
        )
        .expanduser()
        .resolve()
    )

    if not project_root.is_dir():
        raise NotADirectoryError(
            "project directory does not exist: "
            f"{project_root}"
        )

    results: list[
        CanonicalBenchmarkVariantResult
    ] = []

    for variant in domain_plan.variants:
        bundles = (
            run_sets[
                variant.name
            ]
        )

        aggregation = (
            aggregate_measured_canonical_benchmark_runs(
                bundles
            )
        )

        result = (
            create_canonical_benchmark_result(
                benchmark_plan_id=(
                    plan.plan_id
                ),
                variant=variant,
                aggregation=aggregation,
            )
        )

        artifact = (
            materialize_benchmark_result(
                result,
                project=project_root,
            )
        )

        results.append(
            CanonicalBenchmarkVariantResult(
                variant=variant,
                aggregation=aggregation,
                result=result,
                artifact=artifact,
            )
        )

    return CanonicalBenchmarkSuite(
        benchmark_plan_id=(
            plan.plan_id
        ),
        variants=tuple(
            results
        ),
    )


__all__ = [
    "CanonicalBenchmarkSuite",
    "CanonicalBenchmarkSuiteError",
    "CanonicalBenchmarkSuiteInputError",
    "CanonicalBenchmarkVariantResult",
    "assemble_canonical_benchmark_suite",
]
