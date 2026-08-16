"""Resolved optimization plans for the Nodrix optimization domain."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from .benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from .manifest import PipelineManifest
from .planning import (
    OPTIMIZATION_SCHEMA,
    optimization_spec,
)


OPTIMIZATION_NOTE = (
    "Candidates are separate benchmark variants; "
    "the source manifest is unchanged."
)


@dataclass(frozen=True, slots=True)
class OptimizationPlan:
    """Exact resolved candidate set for one optimization operation."""

    pipeline: Path
    pipeline_name: str
    objectives: Mapping[str, Any]
    constraints: Mapping[str, Any]
    benchmark_plan: BenchmarkPlan
    run_benchmarks: bool = False

    def __post_init__(self) -> None:
        pipeline = Path(
            self.pipeline
        ).expanduser().resolve()

        object.__setattr__(
            self,
            "pipeline",
            pipeline,
        )

        name = self.pipeline_name.strip()

        if not name:
            raise ValueError(
                "optimization pipeline_name must be non-empty"
            )

        object.__setattr__(
            self,
            "pipeline_name",
            name,
        )

        if not isinstance(
            self.benchmark_plan,
            BenchmarkPlan,
        ):
            raise TypeError(
                "benchmark_plan must be a BenchmarkPlan"
            )

        if not isinstance(
            self.run_benchmarks,
            bool,
        ):
            raise TypeError(
                "run_benchmarks must be a boolean"
            )

        benchmark_pipeline = (
            self.benchmark_plan.pipeline
            .expanduser()
            .resolve()
        )

        if benchmark_pipeline != pipeline:
            raise ValueError(
                "optimization benchmark plan must target "
                "the same pipeline"
            )

        if not isinstance(
            self.objectives,
            Mapping,
        ):
            raise TypeError(
                "objectives must be a mapping"
            )

        if not isinstance(
            self.constraints,
            Mapping,
        ):
            raise TypeError(
                "constraints must be a mapping"
            )

        object.__setattr__(
            self,
            "objectives",
            MappingProxyType(
                dict(self.objectives)
            ),
        )

        object.__setattr__(
            self,
            "constraints",
            MappingProxyType(
                dict(self.constraints)
            ),
        )

    @property
    def variants(
        self,
    ) -> tuple[BenchmarkVariant, ...]:
        return self.benchmark_plan.variants

    def as_dict(self) -> dict[str, Any]:
        variants: dict[str, dict[str, Any]] = {}

        for variant in self.variants:
            raw: dict[str, Any] = {
                "set": list(
                    variant.set_values
                ),
            }

            if variant.profile is not None:
                raw["profile"] = (
                    variant.profile
                )

            if variant.block_values:
                raw["block"] = list(
                    variant.block_values
                )

            variants[variant.name] = raw

        return {
            "schema": OPTIMIZATION_SCHEMA,
            "pipeline": self.pipeline_name,
            "objectives": dict(
                self.objectives
            ),
            "constraints": dict(
                self.constraints
            ),
            "variants": variants,
            "applied": False,
            "note": OPTIMIZATION_NOTE,
        }


def build_optimization_plan(
    pipeline: str | Path,
    manifest: PipelineManifest,
    *,
    max_variants: int = 12,
    objectives: Mapping[str, Any] | None = None,
    constraints: Mapping[str, Any] | None = None,
) -> OptimizationPlan:
    """Resolve optimization candidates without writing artifacts."""

    path = Path(
        pipeline
    ).expanduser().resolve()

    if not path.is_file():
        raise FileNotFoundError(
            f"Optimization pipeline does not exist: {path}"
        )

    result = optimization_spec(
        manifest,
        max_variants=max_variants,
        objectives=objectives,
        constraints=constraints,
    )

    raw_variants = result.get(
        "variants"
    )

    if not isinstance(
        raw_variants,
        Mapping,
    ):
        raise TypeError(
            "optimization variants must be a mapping"
        )

    variants = tuple(
        BenchmarkVariant.from_mapping(
            str(name),
            raw,
        )
        for name, raw
        in raw_variants.items()
    )

    benchmark_plan = BenchmarkPlan(
        pipeline=path,
        repeat=3,
        warmup=1,
        variants=variants,
    )

    return OptimizationPlan(
        pipeline=path,
        pipeline_name=str(
            result["pipeline"]
        ),
        objectives=dict(
            result.get("objectives") or {}
        ),
        constraints=dict(
            result.get("constraints") or {}
        ),
        benchmark_plan=benchmark_plan,
    )



def optimization_benchmark_spec(
    plan: OptimizationPlan,
) -> dict[str, Any]:
    """Materialize the benchmark specification represented by an exact plan."""

    if not isinstance(
        plan,
        OptimizationPlan,
    ):
        raise TypeError(
            "plan must be an OptimizationPlan"
        )

    rendered = plan.as_dict()

    return {
        "version": 1,
        "pipeline": str(
            plan.pipeline
        ),
        "warmup": (
            plan.benchmark_plan.warmup
        ),
        "repeat": (
            plan.benchmark_plan.repeat
        ),
        "variants": dict(
            rendered["variants"]
        ),
    }


def optimization_result(
    plan: OptimizationPlan,
    *,
    benchmark: Mapping[str, Any] | None = None,
    recommendation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the legacy/public optimization result from one exact plan."""

    if not isinstance(
        plan,
        OptimizationPlan,
    ):
        raise TypeError(
            "plan must be an OptimizationPlan"
        )

    result = plan.as_dict()

    if benchmark is not None:
        if not isinstance(
            benchmark,
            Mapping,
        ):
            raise TypeError(
                "benchmark must be a mapping or None"
            )

        result["benchmark"] = dict(
            benchmark
        )

    if recommendation is not None:
        if not isinstance(
            recommendation,
            Mapping,
        ):
            raise TypeError(
                "recommendation must be a mapping or None"
            )

        result["recommendation"] = dict(
            recommendation
        )

    return result


def write_optimization_plan(
    plan: OptimizationPlan,
    output_dir: str | Path,
    *,
    benchmark: Mapping[str, Any] | None = None,
    recommendation: Mapping[str, Any] | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """Write artifacts from an already resolved OptimizationPlan."""

    if not isinstance(
        plan,
        OptimizationPlan,
    ):
        raise TypeError(
            "plan must be an OptimizationPlan"
        )

    root = Path(
        output_dir
    ).expanduser().resolve()

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    spec_path = (
        root / "benchmark-variants.yaml"
    )

    report_path = (
        root / "optimization-plan.json"
    )

    spec = optimization_benchmark_spec(
        plan
    )

    result = optimization_result(
        plan,
        benchmark=benchmark,
        recommendation=recommendation,
    )

    spec_path.write_text(
        yaml.safe_dump(
            spec,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report_path.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return (
        spec_path,
        report_path,
        result,
    )


__all__ = [
    "OPTIMIZATION_NOTE",
    "OptimizationPlan",
    "build_optimization_plan",
    "optimization_benchmark_spec",
    "optimization_result",
    "write_optimization_plan",
]
