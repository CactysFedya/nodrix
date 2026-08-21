"""Strict coordination of canonical Benchmark warm-up and measured Runs.

Every invocation is an ordinary persisted canonical Run.  Warm-up Runs remain
historical evidence but are excluded from Benchmark aggregation.

This module coordinates repetitions only.  It deliberately knows nothing
about HybridPipelineRuntime, legacy report dictionaries or a concrete System
executor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from .run_bundle import (
    CanonicalRunBundle,
)


BenchmarkRunPhase = Literal[
    "warmup",
    "measured",
]


class CanonicalMeasuredRunError(
    RuntimeError
):
    """Base error for canonical Benchmark Run coordination."""


class CanonicalMeasuredRunContractError(
    CanonicalMeasuredRunError
):
    """A measured-run executor violated the canonical Run contract."""


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalBenchmarkRunRequest:
    """One exact Run requested by the Benchmark coordinator."""

    plan: BenchmarkPlan
    variant: BenchmarkVariant
    phase: BenchmarkRunPhase
    iteration: int

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.plan,
            BenchmarkPlan,
        ):
            raise TypeError(
                "plan must be a BenchmarkPlan"
            )

        if not isinstance(
            self.variant,
            BenchmarkVariant,
        ):
            raise TypeError(
                "variant must be a BenchmarkVariant"
            )

        if self.phase not in {
            "warmup",
            "measured",
        }:
            raise ValueError(
                "phase must be 'warmup' or 'measured'"
            )

        if not isinstance(
            self.iteration,
            int,
        ):
            raise TypeError(
                "iteration must be an integer"
            )

        if self.iteration < 0:
            raise ValueError(
                "iteration must be non-negative"
            )


CanonicalBenchmarkRunCallable = Callable[
    [
        CanonicalBenchmarkRunRequest,
    ],
    CanonicalRunBundle,
]


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalBenchmarkVariantRuns:
    """All canonical Runs executed for one Benchmark variant."""

    variant: BenchmarkVariant
    warmup: tuple[
        CanonicalRunBundle,
        ...,
    ]
    measured: tuple[
        CanonicalRunBundle,
        ...,
    ]

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

        for field_name in (
            "warmup",
            "measured",
        ):
            values = getattr(
                self,
                field_name,
            )

            if not isinstance(
                values,
                tuple,
            ):
                raise TypeError(
                    f"{field_name} must be a tuple"
                )

            for bundle in values:
                if not isinstance(
                    bundle,
                    CanonicalRunBundle,
                ):
                    raise TypeError(
                        f"{field_name} must contain "
                        "CanonicalRunBundle values"
                    )

    @property
    def warmup_run_ids(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            bundle.session.run_id
            for bundle
            in self.warmup
        )

    @property
    def measured_run_ids(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            bundle.session.run_id
            for bundle
            in self.measured
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "variant": (
                self.variant.name
            ),
            "warmupRuns": list(
                self.warmup_run_ids
            ),
            "measuredRuns": list(
                self.measured_run_ids
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalBenchmarkRuns:
    """All canonical warm-up/measured Runs for one Benchmark Plan."""

    variants: tuple[
        CanonicalBenchmarkVariantRuns,
        ...,
    ]

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.variants,
            tuple,
        ):
            raise TypeError(
                "variants must be a tuple"
            )

        names: list[str] = []
        run_ids: set[str] = set()

        for item in self.variants:
            if not isinstance(
                item,
                CanonicalBenchmarkVariantRuns,
            ):
                raise TypeError(
                    "variants must contain "
                    "CanonicalBenchmarkVariantRuns"
                )

            names.append(
                item.variant.name
            )

            for run_id in (
                *item.warmup_run_ids,
                *item.measured_run_ids,
            ):
                if run_id in run_ids:
                    raise (
                        CanonicalMeasuredRunContractError(
                            "one canonical Run cannot satisfy "
                            "multiple Benchmark executions: "
                            f"{run_id}"
                        )
                    )

                run_ids.add(
                    run_id
                )

        if len(
            names
        ) != len(
            set(
                names
            )
        ):
            raise ValueError(
                "Benchmark variant names must be unique"
            )

    @property
    def measured_runs(
        self,
    ) -> dict[
        str,
        tuple[
            CanonicalRunBundle,
            ...,
        ],
    ]:
        """Return the strict input expected by canonical suite assembly."""

        return {
            item.variant.name: (
                item.measured
            )
            for item
            in self.variants
        }

    @property
    def warmup_run_ids(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            run_id
            for item
            in self.variants
            for run_id
            in item.warmup_run_ids
        )

    @property
    def measured_run_ids(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            run_id
            for item
            in self.variants
            for run_id
            in item.measured_run_ids
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "variants": [
                item.to_dict()
                for item
                in self.variants
            ],
        }


def _execute_request(
    request: CanonicalBenchmarkRunRequest,
    *,
    run_callable: CanonicalBenchmarkRunCallable,
) -> CanonicalRunBundle:
    bundle = run_callable(
        request
    )

    if not isinstance(
        bundle,
        CanonicalRunBundle,
    ):
        raise CanonicalMeasuredRunContractError(
            "canonical Benchmark run_callable "
            "must return CanonicalRunBundle"
        )

    return bundle


def execute_canonical_benchmark_runs(
    plan: BenchmarkPlan,
    *,
    run_callable: CanonicalBenchmarkRunCallable,
) -> CanonicalBenchmarkRuns:
    """Execute all warm-up/measured repetitions as ordinary canonical Runs."""

    if not isinstance(
        plan,
        BenchmarkPlan,
    ):
        raise TypeError(
            "plan must be a BenchmarkPlan"
        )

    if not callable(
        run_callable
    ):
        raise TypeError(
            "run_callable must be callable"
        )

    variants: list[
        CanonicalBenchmarkVariantRuns
    ] = []

    seen_run_ids: set[
        str
    ] = set()

    def record(
        bundle: CanonicalRunBundle,
    ) -> CanonicalRunBundle:
        run_id = (
            bundle.session.run_id
        )

        if run_id in seen_run_ids:
            raise CanonicalMeasuredRunContractError(
                "canonical Benchmark run_callable "
                "reused Run identity: "
                f"{run_id}"
            )

        seen_run_ids.add(
            run_id
        )

        return bundle

    for variant in plan.variants:
        warmup: list[
            CanonicalRunBundle
        ] = []

        measured: list[
            CanonicalRunBundle
        ] = []

        for iteration in range(
            plan.warmup
        ):
            request = (
                CanonicalBenchmarkRunRequest(
                    plan=plan,
                    variant=variant,
                    phase="warmup",
                    iteration=iteration,
                )
            )

            warmup.append(
                record(
                    _execute_request(
                        request,
                        run_callable=(
                            run_callable
                        ),
                    )
                )
            )

        for iteration in range(
            plan.repeat
        ):
            request = (
                CanonicalBenchmarkRunRequest(
                    plan=plan,
                    variant=variant,
                    phase="measured",
                    iteration=iteration,
                )
            )

            measured.append(
                record(
                    _execute_request(
                        request,
                        run_callable=(
                            run_callable
                        ),
                    )
                )
            )

        variants.append(
            CanonicalBenchmarkVariantRuns(
                variant=variant,
                warmup=tuple(
                    warmup
                ),
                measured=tuple(
                    measured
                ),
            )
        )

    return CanonicalBenchmarkRuns(
        variants=tuple(
            variants
        )
    )


__all__ = [
    "BenchmarkRunPhase",
    "CanonicalBenchmarkRunCallable",
    "CanonicalBenchmarkRunRequest",
    "CanonicalBenchmarkRuns",
    "CanonicalBenchmarkVariantRuns",
    "CanonicalMeasuredRunContractError",
    "CanonicalMeasuredRunError",
    "execute_canonical_benchmark_runs",
]
