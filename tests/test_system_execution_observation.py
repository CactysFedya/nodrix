from __future__ import annotations

import pytest

from nodrix.system import (
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionHealthState,
    ExecutionObservation,
    SystemExecutionStatus,
)


def test_execution_observation_defaults_to_unknown() -> None:
    observation = ExecutionObservation()

    assert observation.ready is None
    assert (
        observation.health
        is ExecutionHealthState.UNKNOWN
    )
    assert observation.message is None


def test_execution_observation_represents_ready_healthy_execution() -> None:
    observation = ExecutionObservation(
        ready=True,
        health=ExecutionHealthState.HEALTHY,
        message="all runtime components are ready",
    )

    backend_status = BackendExecutionStatus(
        backend="local",
        execution_id="local-001",
        state=BackendExecutionState.RUNNING,
        observation=observation,
    )

    system_status = SystemExecutionStatus(
        execution_id="system-001",
        state=BackendExecutionState.RUNNING,
        observation=observation,
    )

    assert backend_status.observation == observation
    assert system_status.observation == observation


def test_execution_statuses_remain_backward_compatible_without_observation() -> None:
    backend_status = BackendExecutionStatus(
        backend="local",
        execution_id="local-001",
        state=BackendExecutionState.RUNNING,
    )

    system_status = SystemExecutionStatus(
        execution_id="system-001",
        state=BackendExecutionState.RUNNING,
    )

    assert backend_status.observation is None
    assert system_status.observation is None


def test_execution_observation_rejects_non_boolean_readiness() -> None:
    with pytest.raises(
        TypeError,
        match="ready must be a bool or None",
    ):
        ExecutionObservation(
            ready="yes",  # type: ignore[arg-type]
        )


def test_execution_observation_rejects_noncanonical_health() -> None:
    with pytest.raises(
        TypeError,
        match="health must be an ExecutionHealthState",
    ):
        ExecutionObservation(
            health="healthy",  # type: ignore[arg-type]
        )


def test_backend_status_rejects_invalid_observation() -> None:
    with pytest.raises(
        TypeError,
        match="BackendExecutionStatus.observation",
    ):
        BackendExecutionStatus(
            backend="local",
            execution_id="local-001",
            state=BackendExecutionState.RUNNING,
            observation={},  # type: ignore[arg-type]
        )


def test_system_status_rejects_invalid_observation() -> None:
    with pytest.raises(
        TypeError,
        match="SystemExecutionStatus.observation",
    ):
        SystemExecutionStatus(
            execution_id="system-001",
            state=BackendExecutionState.RUNNING,
            observation={},  # type: ignore[arg-type]
        )
