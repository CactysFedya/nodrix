from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nodrix.system.connection_execution import (
    ConnectionExecutionResolutionError,
    ResolvedConnectionExecutionPolicy,
    resolve_connection_execution_defaults,
)
from nodrix.system.planning import (
    PlannedConnection,
)


def test_connection_execution_has_explicit_canonical_base_policy():
    resolved = (
        resolve_connection_execution_defaults(
            {}
        )
    )

    assert resolved.queue.capacity == 8
    assert resolved.queue.policy == "block"

    assert resolved.memory.domain == "auto"
    assert resolved.memory.allow_copy is True


def test_connection_execution_resolves_queue_defaults():
    resolved = (
        resolve_connection_execution_defaults(
            {
                "queue": {
                    "capacity": 2,
                    "policy": "drop_oldest",
                },
            }
        )
    )

    assert resolved.queue.capacity == 2

    assert (
        resolved.queue.policy
        == "drop_oldest"
    )

    assert resolved.memory.domain == "auto"
    assert resolved.memory.allow_copy is True


def test_connection_execution_resolves_memory_defaults():
    resolved = (
        resolve_connection_execution_defaults(
            {
                "memory": {
                    "domain": "shared",
                    "allow_copy": False,
                },
            }
        )
    )

    assert resolved.queue.capacity == 8
    assert resolved.queue.policy == "block"

    assert resolved.memory.domain == "shared"
    assert resolved.memory.allow_copy is False


def test_connection_execution_supports_partial_sections():
    resolved = (
        resolve_connection_execution_defaults(
            {
                "queue": {
                    "capacity": 5,
                },
                "memory": {
                    "allow_copy": False,
                },
            }
        )
    )

    assert resolved.queue.capacity == 5
    assert resolved.queue.policy == "block"

    assert resolved.memory.domain == "auto"
    assert resolved.memory.allow_copy is False


@pytest.mark.parametrize(
    "policy",
    [
        "",
        "unbounded",
        "fifo",
    ],
)
def test_connection_execution_rejects_unknown_queue_policy(
    policy,
):
    with pytest.raises(
        ConnectionExecutionResolutionError,
    ):
        resolve_connection_execution_defaults(
            {
                "queue": {
                    "policy": policy,
                },
            }
        )


@pytest.mark.parametrize(
    "capacity",
    [
        0,
        -1,
        True,
        "8",
    ],
)
def test_connection_execution_rejects_invalid_capacity(
    capacity,
):
    with pytest.raises(
        ConnectionExecutionResolutionError,
    ):
        resolve_connection_execution_defaults(
            {
                "queue": {
                    "capacity": capacity,
                },
            }
        )


def test_connection_execution_rejects_unknown_fields():
    with pytest.raises(
        ConnectionExecutionResolutionError,
        match="mystery",
    ):
        resolve_connection_execution_defaults(
            {
                "mystery": {
                    "enabled": True,
                },
            }
        )


def test_connection_execution_rejects_invalid_allow_copy():
    with pytest.raises(
        ConnectionExecutionResolutionError,
        match="allow_copy",
    ):
        resolve_connection_execution_defaults(
            {
                "memory": {
                    "allow_copy": 1,
                },
            }
        )


def test_planned_connection_carries_resolved_execution_policy():
    connection = PlannedConnection(
        ordinal=0,
        graph="main",
        **{
            "from": "source.output",
            "to": "sink.input",
        },
        type_id="core.object",
        placement_target="local",
        backend="local",
        execution=(
            resolve_connection_execution_defaults(
                {
                    "queue": {
                        "capacity": 3,
                        "policy": "latest",
                    },
                    "memory": {
                        "domain": "shared",
                        "allow_copy": False,
                    },
                }
            )
        ),
    )

    assert connection.execution.queue.capacity == 3

    assert (
        connection.execution.queue.policy
        == "latest"
    )

    assert (
        connection.execution.memory.domain
        == "shared"
    )

    assert (
        connection.execution.memory.allow_copy
        is False
    )


def test_planned_connection_base_policy_is_canonical():
    connection = PlannedConnection(
        ordinal=0,
        graph="main",
        **{
            "from": "source.output",
            "to": "sink.input",
        },
        placement_target="local",
        backend="local",
    )

    assert isinstance(
        connection.execution,
        ResolvedConnectionExecutionPolicy,
    )

    assert connection.execution.queue.capacity == 8
    assert connection.execution.queue.policy == "block"


def test_connection_execution_has_no_legacy_runtime_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "connection_execution.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        source,
        filename=str(path),
    )

    forbidden_modules = {
        "manifest",
        "manifest_model",
        "compatibility",
        "local_backend",
        "hybrid_runtime",
        "runtime_builder",
    }

    forbidden_names = {
        "EdgeConfig",
        "QueueConfig",
        "RuntimeConfig",
        "PipelineManifest",
        "LocalBackend",
        "HybridPipelineRuntime",
    }

    for node in ast.walk(tree):
        if not isinstance(
            node,
            ast.ImportFrom,
        ):
            continue

        module = (
            node.module
            or ""
        )

        assert (
            module.split(".")[-1]
            not in forbidden_modules
        )

        for alias in node.names:
            assert (
                alias.name
                not in forbidden_names
            )


def test_planner_resolves_connection_execution_before_runtime():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "planning.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    assert (
        "resolve_connection_execution_defaults("
        in source
    )

    assert (
        "execution=connection_execution"
        in source
    )

    assert (
        'connection.extensions.get("legacy")'
        not in source
    )


def test_planner_reports_invalid_connection_execution_as_plan415():
    from nodrix.system import (
        Connection,
        Graph,
        NodeInstance,
        SystemModel,
    )
    from nodrix.system.execution_context import (
        SystemExecutionContext,
    )
    from nodrix.system.planning import (
        SystemPlanningError,
        plan_system,
    )

    system = SystemModel(
        name="invalid-edge-policy",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="source",
                        uses="demo.source",
                    ),
                    NodeInstance(
                        name="sink",
                        uses="demo.sink",
                    ),
                ),
                connections=(
                    Connection(
                        **{
                            "from": "source.output",
                            "to": "sink.input",
                        }
                    ),
                ),
            ),
        ),
    )

    context = SystemExecutionContext(
        edge_defaults={
            "queue": {
                "capacity": 0,
            },
        },
    )

    with pytest.raises(
        SystemPlanningError,
    ) as captured:
        plan_system(
            system,
            execution_context=context,
        )

    assert captured.value.code == "PLAN415"

    assert (
        captured.value.path
        == "execution_context.edge_defaults"
    )
