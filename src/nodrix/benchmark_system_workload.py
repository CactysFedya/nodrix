"""Canonical Benchmark authoring adapter for System workloads.

The measured-run executor operates only on resolved canonical System workloads.
This module is the explicit authoring bridge from the current BenchmarkPlan /
BenchmarkVariant model into that execution boundary.

Legacy Pipeline ``set`` and ``block`` variant syntax is deliberately rejected
here.  Canonical System Benchmarking must never silently reinterpret legacy
Pipeline mutation semantics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .benchmark_measured_runs import (
    CanonicalBenchmarkRunRequest,
)
from .benchmark_system_identity import (
    CanonicalBenchmarkWorkloadSet,
    canonical_benchmark_workload_set,
)
from .benchmark_system_runner import (
    CanonicalSystemBenchmarkWorkload,
)
from .benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from .execution_policy import (
    ExecutionPolicy,
)
from .observability_profiles import (
    ObservabilityProfileName,
    resolve_observability_profile,
)
from .system.orchestration import (
    SystemOrchestrator,
)
from .system_workload import (
    ResolvedSystemWorkload,
    SystemCatalogProvider,
    resolve_system_workload,
)


CanonicalSystemOrchestratorFactory = Callable[
    [
        ResolvedSystemWorkload,
    ],
    SystemOrchestrator,
]


class CanonicalBenchmarkVariantResolutionError(
    RuntimeError
):
    """Benchmark variant cannot be represented by canonical System semantics."""


class CanonicalBenchmarkSystemWorkloadResolver:
    """Resolve Benchmark variants once and create fresh execution machinery.

    Immutable Definition/ExecutionContext/Plan semantics are cached per
    BenchmarkPlan variant.  A fresh SystemOrchestrator is still created for
    every Run so runtime state can never leak between warmup or measured
    repetitions.
    """

    def __init__(
        self,
        *,
        orchestrator_factory: (
            CanonicalSystemOrchestratorFactory
        ),
        catalog_provider: (
            SystemCatalogProvider | None
        ) = None,
        execution_policy: (
            ExecutionPolicy | None
        ) = None,
    ) -> None:
        if not callable(
            orchestrator_factory
        ):
            raise TypeError(
                "orchestrator_factory must be callable"
            )

        if (
            catalog_provider is not None
            and not callable(
                catalog_provider
            )
        ):
            raise TypeError(
                "catalog_provider must be callable "
                "or None"
            )

        if (
            execution_policy is not None
            and not isinstance(
                execution_policy,
                ExecutionPolicy,
            )
        ):
            raise TypeError(
                "execution_policy must be an "
                "ExecutionPolicy or None"
            )

        self._orchestrator_factory = (
            orchestrator_factory
        )

        self._catalog_provider = (
            catalog_provider
        )

        # Benchmark observability is an ExecutionPolicy choice, completely
        # independent from BenchmarkVariant.profile / Project Profile.
        self._execution_policy = (
            execution_policy
            if execution_policy is not None
            else resolve_observability_profile(
                ObservabilityProfileName.BENCHMARK
            )
        )

        self._cache: dict[
            tuple[
                int,
                str,
            ],
            ResolvedSystemWorkload,
        ] = {}

    def clear_cache(
        self,
    ) -> None:
        """Forget resolved authoring semantics without touching live Runs."""

        self._cache.clear()

    @property
    def cached_variant_count(
        self,
    ) -> int:
        return len(
            self._cache
        )

    def _resolved_variant(
        self,
        plan: BenchmarkPlan,
        variant: BenchmarkVariant,
    ) -> ResolvedSystemWorkload:
        """Resolve one exact canonical System Benchmark variant.

        Resolution is cached by BenchmarkPlan object identity and canonical
        variant name.  Both Benchmark Result identity and actual Runs consume
        this same cached ResolvedSystemWorkload so Definition/Plan provenance
        cannot diverge between planning and execution.
        """

        if not isinstance(
            plan,
            BenchmarkPlan,
        ):
            raise TypeError(
                "plan must be a BenchmarkPlan"
            )

        if not isinstance(
            variant,
            BenchmarkVariant,
        ):
            raise TypeError(
                "variant must be a BenchmarkVariant"
            )

        canonical_variant = next(
            (
                candidate
                for candidate
                in plan.variants
                if candidate.name
                == variant.name
            ),
            None,
        )

        if (
            canonical_variant is None
            or canonical_variant
            != variant
        ):
            raise (
                CanonicalBenchmarkVariantResolutionError(
                    "Benchmark variant must match "
                    "the exact variant declared by "
                    "its BenchmarkPlan"
                )
            )

        # These fields belong to the historical Pipeline benchmark authoring
        # model. Guessing a System equivalent would create hidden fallback
        # semantics and make Definition/Plan provenance dishonest.
        if (
            canonical_variant.set_values
            or canonical_variant.block_values
        ):
            fields: list[
                str
            ] = []

            if canonical_variant.set_values:
                fields.append(
                    "set"
                )

            if canonical_variant.block_values:
                fields.append(
                    "block"
                )

            raise (
                CanonicalBenchmarkVariantResolutionError(
                    "canonical System Benchmark does not "
                    "support legacy variant "
                    + "/".join(
                        fields
                    )
                    + " overrides; express workload "
                    "differences through System Config, "
                    "Project Profile or canonical "
                    "System parameters"
                )
            )

        key = (
            id(
                plan
            ),
            canonical_variant.name,
        )

        cached = self._cache.get(
            key
        )

        if cached is not None:
            return cached

        # BenchmarkPlan.pipeline is retained by the current compatibility
        # authoring schema. Canonical mode does not convert it as a Pipeline:
        # the referenced document must itself load as a canonical System.
        source = (
            Path(
                plan.pipeline
            )
            .expanduser()
            .resolve()
        )

        resolved = resolve_system_workload(
            source,
            # In canonical System mode this field has one explicit meaning:
            # Project Profile, matching ``plyctl system --profile``.
            profile=(
                canonical_variant.profile
            ),
            catalog_provider=(
                self._catalog_provider
            ),
        )

        self._cache[
            key
        ] = resolved

        return resolved

    def _resolved(
        self,
        request: CanonicalBenchmarkRunRequest,
    ) -> ResolvedSystemWorkload:
        """Resolve the exact workload requested by one canonical Run."""

        if not isinstance(
            request,
            CanonicalBenchmarkRunRequest,
        ):
            raise TypeError(
                "request must be a "
                "CanonicalBenchmarkRunRequest"
            )

        return self._resolved_variant(
            request.plan,
            request.variant,
        )

    def workload_set(
        self,
        plan: BenchmarkPlan,
        *,
        name: str | None = None,
    ) -> CanonicalBenchmarkWorkloadSet:
        """Resolve exact variant Plans and build canonical Benchmark identity.

        This method intentionally shares ``_resolved_variant`` with Run
        execution. Calling it before warmup/measured Runs populates the same
        cache later consumed by ``__call__``.
        """

        if not isinstance(
            plan,
            BenchmarkPlan,
        ):
            raise TypeError(
                "plan must be a BenchmarkPlan"
            )

        variant_plans = {
            variant.name: (
                self._resolved_variant(
                    plan,
                    variant,
                ).plan
            )
            for variant
            in plan.variants
        }

        return canonical_benchmark_workload_set(
            plan,
            variant_plans=variant_plans,
            name=name,
        )


    def __call__(
        self,
        request: CanonicalBenchmarkRunRequest,
    ) -> CanonicalSystemBenchmarkWorkload:
        if not isinstance(
            request,
            CanonicalBenchmarkRunRequest,
        ):
            raise TypeError(
                "request must be a "
                "CanonicalBenchmarkRunRequest"
            )

        resolved = self._resolved(
            request
        )

        orchestrator = (
            self._orchestrator_factory(
                resolved
            )
        )

        if not isinstance(
            orchestrator,
            SystemOrchestrator,
        ):
            raise TypeError(
                "orchestrator_factory must return "
                "SystemOrchestrator"
            )

        return CanonicalSystemBenchmarkWorkload(
            system_definition=(
                resolved.system_definition
            ),
            plan=resolved.plan,
            orchestrator=orchestrator,
            execution_context=(
                resolved.execution_context
            ),
            execution_policy=(
                self._execution_policy
            ),
        )


__all__ = [
    "CanonicalBenchmarkSystemWorkloadResolver",
    "CanonicalBenchmarkVariantResolutionError",
    "CanonicalSystemOrchestratorFactory",
]
