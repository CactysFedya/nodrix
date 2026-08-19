from __future__ import annotations

from dataclasses import (
    FrozenInstanceError,
    fields,
)

import pytest

from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.run_environment import (
    RunEnvironmentPolicy,
)
from nodrix.run_logs import (
    RunLogPolicy,
)


def test_default_execution_policy_is_minimal() -> None:
    policy = ExecutionPolicy()

    assert isinstance(
        policy.environment,
        RunEnvironmentPolicy,
    )
    assert isinstance(
        policy.logs,
        RunLogPolicy,
    )

    # Environment provenance is allowlist-only by default.
    assert tuple(
        policy.environment.variables
    ) == ()

    # Diagnostic logging remains opt-in.
    assert policy.logs.enabled is False


def test_execution_policy_preserves_exact_subpolicies() -> None:
    environment = RunEnvironmentPolicy(
        variables=(
            "ROS_DOMAIN_ID",
            "RMW_IMPLEMENTATION",
        ),
    )

    logs = RunLogPolicy(
        enabled=True,
        categories=(
            "executor",
            "mapping",
        ),
    )

    policy = ExecutionPolicy(
        environment=environment,
        logs=logs,
    )

    assert policy.environment is environment
    assert policy.logs is logs


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    (
        (
            "environment",
            object(),
            "environment must be a RunEnvironmentPolicy",
        ),
        (
            "logs",
            object(),
            "logs must be a RunLogPolicy",
        ),
    ),
)
def test_execution_policy_rejects_invalid_subpolicy(
    field_name,
    value,
    message,
) -> None:
    kwargs = {
        field_name: value,
    }

    with pytest.raises(
        TypeError,
        match=message,
    ):
        ExecutionPolicy(
            **kwargs
        )


def test_execution_policy_is_immutable() -> None:
    policy = ExecutionPolicy()

    with pytest.raises(
        FrozenInstanceError,
    ):
        policy.logs = RunLogPolicy(  # type: ignore[misc]
            enabled=True
        )


def test_execution_policy_v1_has_only_cross_domain_control_plane_fields() -> None:
    names = tuple(
        item.name
        for item in fields(
            ExecutionPolicy
        )
    )

    assert names == (
        "environment",
        "logs",
    )


def test_execution_policy_does_not_duplicate_execution_semantics() -> None:
    names = {
        item.name
        for item in fields(
            ExecutionPolicy
        )
    }

    assert names.isdisjoint(
        {
            "operation",
            "plan",
            "graph",
            "backend",
            "restart",
            "failure",
            "timeout",
            "resources",
            "retention",
            "metrics",
            "artifacts",
            "events",
        }
    )


def test_all_operation_kinds_use_same_policy_type() -> None:
    # ExecutionPolicy deliberately has no OperationKind field.
    # A custom Operation therefore does not need a new policy class.
    policy = ExecutionPolicy()

    assert isinstance(
        policy,
        ExecutionPolicy,
    )
    assert not hasattr(
        policy,
        "operation_kind",
    )
