from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from nodrix.run_metric_policy import (
    RunMetricPolicy,
)


def test_default_metric_policy_is_bounded() -> None:
    policy = RunMetricPolicy()

    assert policy.max_records > 0
    assert policy.max_bytes > 0
    assert policy.max_record_bytes > 0
    assert policy.overflow == "drop"


@pytest.mark.parametrize(
    "field_name",
    (
        "max_records",
        "max_bytes",
        "max_record_bytes",
    ),
)
@pytest.mark.parametrize(
    "value",
    (
        0,
        -1,
        True,
        1.5,
    ),
)
def test_metric_policy_rejects_invalid_limits(
    field_name,
    value,
) -> None:
    with pytest.raises(
        (TypeError, ValueError),
    ):
        RunMetricPolicy(
            **{
                field_name: value,
            }
        )


def test_metric_policy_rejects_unknown_overflow() -> None:
    with pytest.raises(
        ValueError,
        match="expected 'drop'",
    ):
        RunMetricPolicy(
            overflow="rotate"
        )


def test_metric_policy_is_immutable() -> None:
    policy = RunMetricPolicy()

    with pytest.raises(
        FrozenInstanceError,
    ):
        policy.max_bytes = 1  # type: ignore[misc]
