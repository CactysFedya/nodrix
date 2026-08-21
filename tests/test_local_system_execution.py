from __future__ import annotations

import pytest

from nodrix.local_system_execution import (
    build_local_system_orchestrator,
    local_backend_factory,
)
from nodrix.system import (
    ExecutionScope,
    Graph,
    LocalBackend,
    NodeInstance,
    SystemModel,
    Target,
    plan_system,
)


def _mixed_plan():
    return plan_system(
        SystemModel(
            name="local-execution-adapter",
            targets=(
                Target(
                    name="robot",
                    kind="host",
                    properties={
                        "backend": "local",
                    },
                ),
                Target(
                    name="server",
                    kind="host",
                    properties={
                        "backend": "remote",
                    },
                ),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="capture",
                            uses="demo.capture",
                            target="robot",
                        ),
                        NodeInstance(
                            name="analysis",
                            uses="demo.analysis",
                            target="server",
                        ),
                    ),
                ),
            ),
        )
    )


def test_local_factory_binds_only_explicit_local_scope(
    tmp_path,
) -> None:
    project = (
        tmp_path
        / "project"
    )

    working_directory = (
        tmp_path
        / "work"
    )

    run_root = (
        tmp_path
        / "runs"
    )

    factory = local_backend_factory(
        project=project,
        working_directory=(
            working_directory
        ),
        run_root=run_root,
        stop_timeout_seconds=3.5,
    )

    local_scope = ExecutionScope(
        "robot",
        "local",
    )

    remote_scope = ExecutionScope(
        "server",
        "remote",
    )

    backend = factory(
        local_scope
    )

    assert isinstance(
        backend,
        LocalBackend,
    )

    assert (
        backend.project_path
        == project.resolve()
    )

    assert (
        backend.working_directory
        == working_directory.resolve()
    )

    assert (
        backend.run_root
        == run_root.resolve()
    )

    assert (
        backend.stop_timeout_seconds
        == 3.5
    )

    assert (
        backend.scope_name
        == "robot"
    )

    # Explicitly unsupported here. No remote -> local fallback.
    assert (
        factory(
            remote_scope
        )
        is None
    )


def test_local_orchestrator_leaves_nonlocal_scope_unbound() -> None:
    plan = _mixed_plan()

    orchestrator = (
        build_local_system_orchestrator(
            plan
        )
    )

    assert (
        ExecutionScope(
            "robot",
            "local",
        )
        in orchestrator.bindings
    )

    assert (
        ExecutionScope(
            "server",
            "remote",
        )
        not in orchestrator.bindings
    )

    report = (
        orchestrator.validate_plan(
            plan
        )
    )

    assert not report.valid

    assert any(
        item.code
        == "ORCH101"
        and item.scope
        == ExecutionScope(
            "server",
            "remote",
        )
        for item
        in report.errors
    )


@pytest.mark.parametrize(
    "value",
    (
        -1.0,
        -0.001,
    ),
)
def test_local_factory_rejects_negative_stop_timeout(
    value,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            "cannot be negative"
        ),
    ):
        local_backend_factory(
            stop_timeout_seconds=value
        )


def test_local_factory_rejects_boolean_stop_timeout() -> None:
    with pytest.raises(
        TypeError,
        match=(
            "real number"
        ),
    ):
        local_backend_factory(
            stop_timeout_seconds=True
        )
