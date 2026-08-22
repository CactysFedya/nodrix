from __future__ import annotations

import json

import pytest

from nodrix.system import (
    Graph,
    NodeInstance,
    SystemModel,
    plan_system,
)
from nodrix.system.execution_context import (
    SystemExecutionContext,
)
from nodrix.system.node_execution import (
    ResolvedNodeExecutionPolicy,
)
from nodrix.system.planning import (
    SystemPlanningError,
)


def _system(
    *,
    parameters=None,
) -> SystemModel:
    return SystemModel(
        name="node-execution-planning",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                        parameters=(
                            parameters
                            or {}
                        ),
                    ),
                ),
            ),
        ),
    )


def _planned_node(
    system: SystemModel,
    *,
    context: SystemExecutionContext | None = None,
):
    plan = plan_system(
        system,
        execution_context=context,
    )

    return (
        plan,
        plan.graph("main").node("worker"),
    )


def test_planner_materializes_explicit_default_node_execution_policy():
    plan, node = _planned_node(
        _system()
    )

    assert (
        plan.execution_context_sha256
        is None
    )

    assert isinstance(
        node.execution,
        ResolvedNodeExecutionPolicy,
    )

    assert (
        node.execution.synchronization.policy
        == "exact_sequence"
    )

    assert (
        node.execution.synchronization.tolerance_ns
        == 20_000_000
    )

    assert (
        node.execution.execution.isolation
        == "in_process"
    )

    assert (
        node.execution.execution.device
        == "auto"
    )

    assert (
        node.execution.failure.policy
        == "stop_execution"
    )

    assert (
        node.execution.health.on_timeout
        == "report"
    )

    assert (
        node.execution.limits.max_message_bytes
        == 256 * 1024 * 1024
    )


def test_planner_resolves_execution_context_node_defaults():
    context = SystemExecutionContext(
        node_defaults={
            "demo.worker": {
                "parameters": {
                    "workers": 2,
                    "nested": {
                        "device": "cpu",
                        "batch": 1,
                    },
                },
                "synchronization": {
                    "policy": (
                        "approximate_timestamp"
                    ),
                    "tolerance_ms": 7.5,
                },
                "execution": {
                    "isolation": "process",
                    "cpu_affinity": [
                        2,
                        3,
                    ],
                    "device": "cpu",
                },
                "failure": {
                    "policy": "restart",
                    "max_restarts": 5,
                },
                "health": {
                    "timeout_ms": 2500,
                    "on_timeout": (
                        "stop_pipeline"
                    ),
                },
                "resources": {
                    "memory_limit_mb": 256,
                    "cpu_limit": 1.25,
                    "max_message_bytes": (
                        16 * 1024 * 1024
                    ),
                },
            },
        },
    )

    plan, node = _planned_node(
        _system(),
        context=context,
    )

    assert (
        plan.execution_context_sha256
        is not None
    )

    assert node.parameters == {
        "workers": 2,
        "nested": {
            "device": "cpu",
            "batch": 1,
        },
    }

    assert (
        node.execution.synchronization.policy
        == "approximate_timestamp"
    )

    assert (
        node.execution.synchronization.tolerance_ns
        == 7_500_000
    )

    assert (
        node.execution.execution.isolation
        == "process"
    )

    assert (
        node.execution.execution.cpu_affinity
        == (
            2,
            3,
        )
    )

    assert (
        node.execution.execution.device
        == "cpu"
    )

    assert (
        node.execution.failure.policy
        == "restart_node"
    )

    assert (
        node.execution.failure.max_restarts
        == 5
    )

    assert (
        node.execution.health.timeout_ns
        == 2_500_000_000
    )

    assert (
        node.execution.health.on_timeout
        == "stop_execution"
    )

    assert (
        node.execution.limits.memory_limit_mb
        == 256
    )

    assert (
        node.execution.limits.cpu_limit
        == 1.25
    )

    assert (
        node.execution.limits.max_message_bytes
        == 16 * 1024 * 1024
    )


def test_explicit_node_parameters_override_context_defaults_recursively():
    context = SystemExecutionContext(
        node_defaults={
            "demo.worker": {
                "parameters": {
                    "workers": 2,
                    "nested": {
                        "device": "cpu",
                        "batch": 1,
                    },
                },
            },
        },
    )

    _, node = _planned_node(
        _system(
            parameters={
                "workers": 8,
                "nested": {
                    "batch": 4,
                },
            },
        ),
        context=context,
    )

    assert node.parameters == {
        "workers": 8,
        "nested": {
            "device": "cpu",
            "batch": 4,
        },
    }


def test_node_defaults_are_selected_by_node_definition_uses():
    context = SystemExecutionContext(
        node_defaults={
            "other.worker": {
                "parameters": {
                    "should_not_exist": True,
                },
                "failure": {
                    "policy": "restart",
                },
            },
        },
    )

    _, node = _planned_node(
        _system(),
        context=context,
    )

    assert (
        "should_not_exist"
        not in node.parameters
    )

    assert (
        node.execution.failure.policy
        == "stop_execution"
    )


def test_invalid_node_execution_defaults_fail_during_planning():
    context = SystemExecutionContext(
        node_defaults={
            "demo.worker": {
                "target": "other",
            },
        },
    )

    with pytest.raises(
        SystemPlanningError,
    ) as caught:
        plan_system(
            _system(),
            execution_context=context,
        )

    error = caught.value

    assert error.code == "PLAN414"

    assert (
        "execution_context."
        "node_defaults['demo.worker']"
        in error.path
    )

    assert (
        "unsupported fields"
        in error.message
    )


def test_plan_document_contains_only_canonical_failure_vocabulary():
    context = SystemExecutionContext(
        node_defaults={
            "demo.worker": {
                "failure": {
                    "policy": "stop_pipeline",
                },
                "health": {
                    "on_timeout": "restart",
                },
            },
        },
    )

    plan, node = _planned_node(
        _system(),
        context=context,
    )

    assert (
        node.execution.failure.policy
        == "stop_execution"
    )

    assert (
        node.execution.health.on_timeout
        == "restart_node"
    )

    encoded = json.dumps(
        plan.model_dump(
            mode="json",
            by_alias=True,
        ),
        sort_keys=True,
    )

    assert '"stop_execution"' in encoded
    assert '"restart_node"' in encoded

    assert '"stop_pipeline"' not in encoded
    assert '"restart"' not in encoded


def test_execution_context_does_not_change_node_architecture():
    context = SystemExecutionContext(
        node_defaults={
            "demo.worker": {
                "parameters": {
                    "workers": 4,
                },
                "resources": {
                    "memory_limit_mb": 128,
                },
            },
        },
    )

    system = _system()

    _, node = _planned_node(
        system,
        context=context,
    )

    original = (
        system.graph("main").node("worker")
    )

    assert node.uses == original.uses
    assert node.name == original.name
    assert node.resources == original.resources
    assert node.target == "local"
    assert node.backend == "local"
