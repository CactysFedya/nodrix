from __future__ import annotations

from pathlib import Path

import pytest

import nodrix.benchmark_system_workload as module
from nodrix.benchmark_measured_runs import (
    CanonicalBenchmarkRunRequest,
)
from nodrix.benchmark_system_workload import (
    CanonicalBenchmarkSystemWorkloadResolver,
    CanonicalBenchmarkVariantResolutionError,
)
from nodrix.benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from nodrix.observability_profiles import (
    resolve_observability_profile,
)
from nodrix.system import (
    SystemModel,
    SystemOrchestrator,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system_workload import (
    ResolvedSystemWorkload,
)


def _source(
    tmp_path: Path,
) -> Path:
    path = (
        tmp_path
        / "system.yaml"
    )

    # Resolution itself is replaced in these adapter tests.  The source still
    # has to exist because BenchmarkPlan represents a concrete authoring input.
    path.write_text(
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "metadata:\n"
        "  name: benchmark-workload\n",
        encoding="utf-8",
    )

    return path


def _plan(
    tmp_path: Path,
    variant: BenchmarkVariant,
) -> BenchmarkPlan:
    return BenchmarkPlan(
        pipeline=_source(
            tmp_path
        ),
        repeat=2,
        warmup=1,
        variants=(
            variant,
        ),
    )


def _request(
    plan: BenchmarkPlan,
    *,
    phase: str = "measured",
    iteration: int = 0,
) -> CanonicalBenchmarkRunRequest:
    return CanonicalBenchmarkRunRequest(
        plan=plan,
        variant=plan.variants[
            0
        ],
        phase=phase,
        iteration=iteration,
    )


def _resolved(
    source: Path,
    *,
    profile: str | None,
) -> ResolvedSystemWorkload:
    system = SystemModel(
        name="benchmark-workload"
    )

    return ResolvedSystemWorkload(
        source=source,
        project_root=None,
        profile=profile,
        system_definition=system,
        execution_context=None,
        plan=plan_canonical_system(
            system
        ),
    )


def test_canonical_variant_profile_is_explicit_project_profile(
    tmp_path,
    monkeypatch,
) -> None:
    variant = BenchmarkVariant(
        "fast",
        profile="robot-fast",
    )

    plan = _plan(
        tmp_path,
        variant,
    )

    calls: list[
        tuple[
            Path,
            str | None,
        ]
    ] = []

    def resolve(
        path,
        *,
        profile=None,
        catalog_provider=None,
    ):
        del catalog_provider

        source = (
            Path(
                path
            ).resolve()
        )

        calls.append(
            (
                source,
                profile,
            )
        )

        return _resolved(
            source,
            profile=profile,
        )

    monkeypatch.setattr(
        module,
        "resolve_system_workload",
        resolve,
    )

    resolver = (
        CanonicalBenchmarkSystemWorkloadResolver(
            orchestrator_factory=(
                lambda resolved: (
                    SystemOrchestrator(
                        {}
                    )
                )
            )
        )
    )

    workload = resolver(
        _request(
            plan
        )
    )

    assert calls == [
        (
            plan.pipeline.resolve(),
            "robot-fast",
        )
    ]

    assert (
        workload.plan.plan_id
        == _resolved(
            plan.pipeline.resolve(),
            profile="robot-fast",
        ).plan.plan_id
    )


@pytest.mark.parametrize(
    (
        "set_values",
        "block_values",
        "field",
    ),
    (
        (
            (
                "x=1",
            ),
            (),
            "set",
        ),
        (
            (),
            (
                "detector=blocks/yolo.yaml",
            ),
            "block",
        ),
    ),
)
def test_legacy_variant_mutations_fail_fast(
    tmp_path,
    set_values,
    block_values,
    field,
) -> None:
    variant = BenchmarkVariant(
        "legacy",
        set_values=set_values,
        block_values=block_values,
    )

    plan = _plan(
        tmp_path,
        variant,
    )

    resolver = (
        CanonicalBenchmarkSystemWorkloadResolver(
            orchestrator_factory=(
                lambda resolved: (
                    SystemOrchestrator(
                        {}
                    )
                )
            )
        )
    )

    with pytest.raises(
        CanonicalBenchmarkVariantResolutionError,
        match=field,
    ):
        resolver(
            _request(
                plan
            )
        )

    assert (
        resolver.cached_variant_count
        == 0
    )


def test_variant_semantics_are_resolved_once_but_orchestrator_is_fresh(
    tmp_path,
    monkeypatch,
) -> None:
    variant = BenchmarkVariant(
        "default"
    )

    plan = _plan(
        tmp_path,
        variant,
    )

    resolution_count = 0

    def resolve(
        path,
        *,
        profile=None,
        catalog_provider=None,
    ):
        nonlocal resolution_count

        del catalog_provider

        resolution_count += 1

        return _resolved(
            Path(
                path
            ).resolve(),
            profile=profile,
        )

    monkeypatch.setattr(
        module,
        "resolve_system_workload",
        resolve,
    )

    orchestrators: list[
        SystemOrchestrator
    ] = []

    def orchestrator_factory(
        resolved,
    ) -> SystemOrchestrator:
        del resolved

        orchestrator = (
            SystemOrchestrator(
                {}
            )
        )

        orchestrators.append(
            orchestrator
        )

        return orchestrator

    resolver = (
        CanonicalBenchmarkSystemWorkloadResolver(
            orchestrator_factory=(
                orchestrator_factory
            )
        )
    )

    warmup = resolver(
        _request(
            plan,
            phase="warmup",
            iteration=0,
        )
    )

    first = resolver(
        _request(
            plan,
            phase="measured",
            iteration=0,
        )
    )

    second = resolver(
        _request(
            plan,
            phase="measured",
            iteration=1,
        )
    )

    assert (
        resolution_count
        == 1
    )

    assert (
        resolver.cached_variant_count
        == 1
    )

    assert (
        warmup.plan.plan_id
        == first.plan.plan_id
        == second.plan.plan_id
    )

    assert len(
        orchestrators
    ) == 3

    assert (
        warmup.orchestrator
        is not first.orchestrator
    )

    assert (
        first.orchestrator
        is not second.orchestrator
    )


def test_default_policy_is_benchmark_observability_profile(
    tmp_path,
    monkeypatch,
) -> None:
    variant = BenchmarkVariant(
        "default"
    )

    plan = _plan(
        tmp_path,
        variant,
    )

    monkeypatch.setattr(
        module,
        "resolve_system_workload",
        lambda path, **kwargs: _resolved(
            Path(
                path
            ).resolve(),
            profile=kwargs.get(
                "profile"
            ),
        ),
    )

    resolver = (
        CanonicalBenchmarkSystemWorkloadResolver(
            orchestrator_factory=(
                lambda resolved: (
                    SystemOrchestrator(
                        {}
                    )
                )
            )
        )
    )

    workload = resolver(
        _request(
            plan
        )
    )

    assert (
        workload.execution_policy
        == resolve_observability_profile(
            "benchmark"
        )
    )


def test_workload_set_and_runs_share_exact_cached_resolution(
    tmp_path,
    monkeypatch,
) -> None:
    import nodrix.benchmark_system_workload as workload_module
    from nodrix.system import (
        SystemOrchestrator,
    )

    variants = (
        BenchmarkVariant(
            "default",
        ),
        BenchmarkVariant(
            "field",
            profile="field",
        ),
    )

    plan = BenchmarkPlan(
        pipeline=_source(
            tmp_path
        ),
        repeat=2,
        warmup=1,
        variants=variants,
    )

    calls: list[
        tuple[
            Path,
            str | None,
        ]
    ] = []

    resolved_by_profile = {}

    def fake_resolve(
        source,
        *,
        profile=None,
        catalog_provider=None,
    ):
        del catalog_provider

        source = Path(
            source
        )

        calls.append(
            (
                source,
                profile,
            )
        )

        resolved = _resolved(
            source,
            profile=profile,
        )

        resolved_by_profile[
            profile
        ] = resolved

        return resolved

    monkeypatch.setattr(
        workload_module,
        "resolve_system_workload",
        fake_resolve,
    )

    resolver = (
        CanonicalBenchmarkSystemWorkloadResolver(
            orchestrator_factory=(
                lambda resolved: (
                    SystemOrchestrator(
                        {}
                    )
                )
            ),
        )
    )

    workload_set = (
        resolver.workload_set(
            plan
        )
    )

    assert len(
        calls
    ) == 2

    assert [
        profile
        for _,
        profile
        in calls
    ] == [
        None,
        "field",
    ]

    # Rebuilding identity from the same exact BenchmarkPlan object must use
    # the same cached resolved workloads.
    repeated = (
        resolver.workload_set(
            plan
        )
    )

    assert (
        repeated.revision
        == workload_set.revision
    )

    assert len(
        calls
    ) == 2

    for index, variant in enumerate(
        plan.variants
    ):
        request = (
            CanonicalBenchmarkRunRequest(
                plan=plan,
                variant=variant,
                phase="measured",
                iteration=0,
            )
        )

        first = resolver(
            request
        )

        second = resolver(
            request
        )

        resolved = (
            resolved_by_profile[
                variant.profile
            ]
        )

        # The exact PlanRecord used to build workload-set identity is also the
        # exact object passed to every canonical Run.
        assert (
            first.plan
            is resolved.plan
        )

        assert (
            second.plan
            is resolved.plan
        )

        identity_variant = (
            workload_set.variants[
                index
            ]
        )

        assert (
            identity_variant.system_plan_id
            == first.plan.plan_id
        )

        assert (
            identity_variant.system_revision
            == first.plan.subject_revision
        )

        # Runtime state remains fresh even though Definition/Plan resolution
        # is cached.
        assert (
            first.orchestrator
            is not second.orchestrator
        )

    # Identity + all measured Run requests still caused exactly one System
    # resolution per variant.
    assert len(
        calls
    ) == 2


def test_resolver_rejects_variant_that_only_reuses_declared_name(
    tmp_path,
    monkeypatch,
) -> None:
    import nodrix.benchmark_system_workload as workload_module
    from nodrix.system import (
        SystemOrchestrator,
    )

    declared = BenchmarkVariant(
        "default",
        profile="field",
    )

    plan = BenchmarkPlan(
        pipeline=_source(
            tmp_path
        ),
        variants=(
            declared,
        ),
    )

    resolve_calls = 0

    def fake_resolve(
        source,
        *,
        profile=None,
        catalog_provider=None,
    ):
        nonlocal resolve_calls

        del catalog_provider

        resolve_calls += 1

        return _resolved(
            Path(
                source
            ),
            profile=profile,
        )

    monkeypatch.setattr(
        workload_module,
        "resolve_system_workload",
        fake_resolve,
    )

    resolver = (
        CanonicalBenchmarkSystemWorkloadResolver(
            orchestrator_factory=(
                lambda resolved: (
                    SystemOrchestrator(
                        {}
                    )
                )
            ),
        )
    )

    forged = BenchmarkVariant(
        "default",
        profile="different-profile",
    )

    request = (
        CanonicalBenchmarkRunRequest(
            plan=plan,
            variant=forged,
            phase="measured",
            iteration=0,
        )
    )

    with pytest.raises(
        CanonicalBenchmarkVariantResolutionError,
        match=(
            "exact variant declared"
        ),
    ):
        resolver(
            request
        )

    # Invalid requests must not poison or even populate the resolution cache.
    assert resolve_calls == 0
