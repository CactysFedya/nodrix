from __future__ import annotations

from dataclasses import (
    fields,
)

import pytest

from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.observability_profiles import (
    ObservabilityProfileName,
    resolve_observability_profile,
)
from nodrix.run_logs import (
    RunLogPolicy,
)
from nodrix.run_metric_policy import (
    RunMetricPolicy,
)


def test_observability_profile_names_are_stable() -> None:
    assert tuple(
        item.value
        for item
        in ObservabilityProfileName
    ) == (
        "minimal",
        "standard",
        "debug",
        "benchmark",
        "custom",
    )


def test_minimal_profile_keeps_optional_observability_disabled() -> None:
    policy = (
        resolve_observability_profile(
            "minimal"
        )
    )

    assert policy == ExecutionPolicy()

    assert not (
        policy.logs.enabled
    )

    assert (
        policy.metrics
        is None
    )


def test_standard_profile_enables_bounded_logs_and_metrics() -> None:
    policy = (
        resolve_observability_profile(
            ObservabilityProfileName.STANDARD
        )
    )

    assert policy.logs == RunLogPolicy(
        enabled=True,
        min_level="warning",
    )

    assert (
        policy.metrics
        == RunMetricPolicy()
    )


def test_debug_profile_has_larger_bounded_observability_budget() -> None:
    policy = (
        resolve_observability_profile(
            "debug"
        )
    )

    assert (
        policy.logs.enabled
    )

    assert (
        policy.logs.min_level
        == "debug"
    )

    assert (
        policy.logs.max_bytes
        == 16 * 1024 * 1024
    )

    assert (
        policy.logs.max_category_bytes
        == 4 * 1024 * 1024
    )

    assert (
        policy.logs.max_record_bytes
        == 64 * 1024
    )

    assert (
        policy.metrics
        == RunMetricPolicy(
            max_records=250_000,
            max_bytes=16 * 1024 * 1024,
            max_record_bytes=64 * 1024,
        )
    )


def test_benchmark_profile_minimizes_logs_and_prioritizes_metrics() -> None:
    policy = (
        resolve_observability_profile(
            "benchmark"
        )
    )

    assert not (
        policy.logs.enabled
    )

    assert (
        policy.metrics
        == RunMetricPolicy(
            max_records=500_000,
            max_bytes=32 * 1024 * 1024,
            max_record_bytes=64 * 1024,
        )
    )


def test_custom_profile_returns_exact_supplied_execution_policy() -> None:
    custom = ExecutionPolicy(
        logs=RunLogPolicy(
            enabled=True,
            min_level="info",
            max_bytes=8192,
            max_category_bytes=4096,
            max_record_bytes=1024,
        ),
        metrics=RunMetricPolicy(
            max_records=17,
            max_bytes=8192,
            max_record_bytes=1024,
        ),
    )

    resolved = (
        resolve_observability_profile(
            "custom",
            custom_policy=custom,
        )
    )

    assert (
        resolved
        is custom
    )


def test_custom_profile_requires_explicit_policy() -> None:
    with pytest.raises(
        ValueError,
        match="requires custom_policy",
    ):
        resolve_observability_profile(
            "custom"
        )


def test_predefined_profile_rejects_custom_override() -> None:
    with pytest.raises(
        ValueError,
        match="only valid with",
    ):
        resolve_observability_profile(
            "standard",
            custom_policy=ExecutionPolicy(),
        )


@pytest.mark.parametrize(
    "value",
    (
        "",
        "unknown",
        "runtime",
        "realtime-low-latency",
    ),
)
def test_observability_profile_rejects_unknown_name(
    value,
) -> None:
    with pytest.raises(
        ValueError,
        match="unsupported observability profile",
    ):
        resolve_observability_profile(
            value
        )


def test_observability_profile_name_is_normalized() -> None:
    assert (
        resolve_observability_profile(
            "  STANDARD  "
        )
        == resolve_observability_profile(
            "standard"
        )
    )


def test_profile_resolution_is_deterministic() -> None:
    for profile in (
        "minimal",
        "standard",
        "debug",
        "benchmark",
    ):
        first = (
            resolve_observability_profile(
                profile
            )
        )

        second = (
            resolve_observability_profile(
                profile
            )
        )

        assert (
            first
            == second
        )

        assert (
            first
            is not second
        )


def test_observability_profile_cannot_control_lifecycle_events() -> None:
    policy_fields = {
        item.name
        for item in fields(
            ExecutionPolicy
        )
    }

    assert policy_fields == {
        "environment",
        "logs",
        "metrics",
    }

    assert "events" not in policy_fields
    assert "events_enabled" not in policy_fields


def test_observability_profiles_are_distinct_from_project_profiles() -> None:
    # Canonical observability names deliberately do not include the legacy
    # Project/Runtime profile vocabulary.
    names = {
        item.value
        for item
        in ObservabilityProfileName
    }

    assert (
        "realtime-low-latency"
        not in names
    )
