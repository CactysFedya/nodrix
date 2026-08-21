from __future__ import annotations

from types import SimpleNamespace
import threading

import pytest

from nodrix.system import (
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionTiming,
    LocalBackend,
)


def test_execution_timing_accepts_finite_non_negative_duration() -> None:
    timing = ExecutionTiming(
        1.25
    )

    assert (
        timing.duration_seconds
        == 1.25
    )


@pytest.mark.parametrize(
    "value",
    (
        -1.0,
        float("nan"),
        float("inf"),
        float("-inf"),
    ),
)
def test_execution_timing_rejects_invalid_numeric_values(
    value,
) -> None:
    with pytest.raises(
        ValueError
    ):
        ExecutionTiming(
            value
        )


def test_execution_timing_rejects_boolean() -> None:
    with pytest.raises(
        TypeError
    ):
        ExecutionTiming(
            True
        )


def test_backend_status_owns_typed_timing() -> None:
    timing = ExecutionTiming(
        2.5
    )

    status = BackendExecutionStatus(
        backend="test",
        execution_id="execution-test",
        state=(
            BackendExecutionState.COMPLETED
        ),
        timing=timing,
    )

    assert (
        status.timing
        is timing
    )


def test_local_backend_projects_runtime_duration_into_typed_status(
    monkeypatch,
) -> None:
    backend = LocalBackend()

    execution = SimpleNamespace(
        lock=threading.Lock(),
        state=(
            BackendExecutionState.COMPLETED
        ),
        report={
            "status": "completed",
            "duration_seconds": 3.75,
        },
        error=None,
        thread=None,
        runtime=object(),
    )

    monkeypatch.setattr(
        backend,
        "_execution",
        lambda handle: execution,
    )

    status = backend._inspect(
        SimpleNamespace(
            execution_id="local-test",
        )
    )

    assert (
        status.timing
        == ExecutionTiming(
            3.75
        )
    )

    assert (
        status.details[
            "report"
        ][
            "duration_seconds"
        ]
        == 3.75
    )


def test_invalid_optional_runtime_timing_does_not_break_inspection(
    monkeypatch,
) -> None:
    backend = LocalBackend()

    execution = SimpleNamespace(
        lock=threading.Lock(),
        state=(
            BackendExecutionState.COMPLETED
        ),
        report={
            "status": "completed",
            "duration_seconds": "bad",
        },
        error=None,
        thread=None,
        runtime=object(),
    )

    monkeypatch.setattr(
        backend,
        "_execution",
        lambda handle: execution,
    )

    status = backend._inspect(
        SimpleNamespace(
            execution_id="local-test",
        )
    )

    assert (
        status.timing
        is None
    )

    assert (
        "timing_error"
        in status.details
    )


def test_canonical_status_details_promote_exact_single_scope_timing() -> None:
    from nodrix.system.canonical_runtime import (
        _status_details,
    )
    from nodrix.system.orchestration import (
        ExecutionScope,
        ScopeExecutionStatus,
        SystemExecutionStatus,
    )

    status = SystemExecutionStatus(
        execution_id="system-timing-single",
        state=(
            BackendExecutionState.COMPLETED
        ),
        scopes=(
            ScopeExecutionStatus(
                scope=ExecutionScope(
                    target="host",
                    backend="local",
                ),
                status=BackendExecutionStatus(
                    backend="local",
                    execution_id=(
                        "local-timing-single"
                    ),
                    state=(
                        BackendExecutionState.COMPLETED
                    ),
                    timing=ExecutionTiming(
                        3.75
                    ),
                ),
            ),
        ),
    )

    details = _status_details(
        status
    )

    assert (
        details[
            "backend_timings"
        ]
        == (
            {
                "target": "host",
                "backend": "local",
                "execution_id": (
                    "local-timing-single"
                ),
                "duration_seconds": 3.75,
            },
        )
    )

    assert (
        details[
            "execution_timing"
        ]
        == {
            "source": "backend",
            "target": "host",
            "backend": "local",
            "execution_id": (
                "local-timing-single"
            ),
            "duration_seconds": 3.75,
        }
    )


def test_canonical_status_details_do_not_synthesize_multi_scope_duration() -> None:
    from nodrix.system.canonical_runtime import (
        _status_details,
    )
    from nodrix.system.orchestration import (
        ExecutionScope,
        ScopeExecutionStatus,
        SystemExecutionStatus,
    )

    status = SystemExecutionStatus(
        execution_id="system-timing-multi",
        state=(
            BackendExecutionState.COMPLETED
        ),
        scopes=(
            ScopeExecutionStatus(
                scope=ExecutionScope(
                    target="host-a",
                    backend="local",
                ),
                status=BackendExecutionStatus(
                    backend="local",
                    execution_id="scope-a",
                    state=(
                        BackendExecutionState.COMPLETED
                    ),
                    timing=ExecutionTiming(
                        2.0
                    ),
                ),
            ),
            ScopeExecutionStatus(
                scope=ExecutionScope(
                    target="host-b",
                    backend="remote",
                ),
                status=BackendExecutionStatus(
                    backend="remote",
                    execution_id="scope-b",
                    state=(
                        BackendExecutionState.COMPLETED
                    ),
                    timing=ExecutionTiming(
                        5.0
                    ),
                ),
            ),
        ),
    )

    details = _status_details(
        status
    )

    assert (
        details[
            "backend_timings"
        ]
        == (
            {
                "target": "host-a",
                "backend": "local",
                "execution_id": "scope-a",
                "duration_seconds": 2.0,
            },
            {
                "target": "host-b",
                "backend": "remote",
                "execution_id": "scope-b",
                "duration_seconds": 5.0,
            },
        )
    )

    # 2 + 5, max(2, 5), etc. are not valid System-duration semantics.
    assert (
        "execution_timing"
        not in details
    )


def test_canonical_status_details_preserve_shape_when_timing_is_unavailable() -> None:
    from nodrix.system.canonical_runtime import (
        _status_details,
    )
    from nodrix.system.orchestration import (
        ExecutionScope,
        ScopeExecutionStatus,
        SystemExecutionStatus,
    )

    status = SystemExecutionStatus(
        execution_id="system-no-timing",
        state=(
            BackendExecutionState.COMPLETED
        ),
        scopes=(
            ScopeExecutionStatus(
                scope=ExecutionScope(
                    target="host",
                    backend="local",
                ),
                status=BackendExecutionStatus(
                    backend="local",
                    execution_id=(
                        "local-no-timing"
                    ),
                    state=(
                        BackendExecutionState.COMPLETED
                    ),
                ),
            ),
        ),
    )

    details = _status_details(
        status
    )

    assert (
        "backend_timings"
        not in details
    )

    assert (
        "execution_timing"
        not in details
    )
