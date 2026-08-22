from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nodrix.system.node_execution import (
    NodeExecutionResolutionError,
    ResolvedNodeExecutionPolicy,
    merge_node_parameters,
    resolve_node_execution_defaults,
)


def test_empty_node_defaults_resolve_to_explicit_canonical_policy():
    parameters, policy = (
        resolve_node_execution_defaults(
            None
        )
    )

    assert parameters == {}

    assert isinstance(
        policy,
        ResolvedNodeExecutionPolicy,
    )

    assert (
        policy.synchronization.policy
        == "exact_sequence"
    )

    assert (
        policy.synchronization.tolerance_ns
        == 20_000_000
    )

    assert (
        policy.execution.isolation
        == "in_process"
    )

    assert (
        policy.execution.cpu_affinity
        == ()
    )

    assert (
        policy.execution.device
        == "auto"
    )

    assert (
        policy.failure.policy
        == "stop_execution"
    )

    assert (
        policy.failure.max_restarts
        == 3
    )

    assert (
        policy.failure.backoff_ms
        == 250
    )

    assert policy.health.timeout_ns == 0

    assert (
        policy.health.on_timeout
        == "report"
    )

    assert (
        policy.limits.memory_limit_mb
        is None
    )

    assert policy.limits.cpu_limit is None

    assert (
        policy.limits.max_message_bytes
        == 256 * 1024 * 1024
    )

    assert dict(
        policy.memory.inputs
    ) == {}

    assert dict(
        policy.memory.outputs
    ) == {}


def test_execution_defaults_are_normalized_to_canonical_policy():
    parameters, policy = (
        resolve_node_execution_defaults(
            {
                "parameters": {
                    "workers": 2,
                },
                "synchronization": {
                    "policy": (
                        "approximate_timestamp"
                    ),
                    "tolerance_ms": 12.5,
                    "trigger_port": "image",
                    "optional_inputs": [
                        "detections",
                    ],
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
                    "max_restarts": 7,
                    "backoff_ms": 125,
                },
                "health": {
                    "timeout_ms": 5000,
                    "on_timeout": (
                        "stop_pipeline"
                    ),
                },
                "resources": {
                    "memory_limit_mb": 512,
                    "cpu_limit": 1.5,
                    "max_message_bytes": (
                        8 * 1024 * 1024
                    ),
                },
                "memory": {
                    "inputs": {
                        "image": {
                            "type": "host",
                        },
                    },
                    "outputs": {
                        "result": {
                            "type": "host",
                        },
                    },
                },
            }
        )
    )

    assert parameters == {
        "workers": 2,
    }

    assert (
        policy.synchronization.policy
        == "approximate_timestamp"
    )

    assert (
        policy.synchronization.tolerance_ns
        == 12_500_000
    )

    assert (
        policy.synchronization.trigger_port
        == "image"
    )

    assert (
        policy.synchronization.optional_inputs
        == (
            "detections",
        )
    )

    assert (
        policy.execution.isolation
        == "process"
    )

    assert (
        policy.execution.cpu_affinity
        == (
            2,
            3,
        )
    )

    assert policy.execution.device == "cpu"

    assert (
        policy.failure.policy
        == "restart_node"
    )

    assert policy.failure.max_restarts == 7

    assert policy.failure.backoff_ms == 125

    assert (
        policy.health.timeout_ns
        == 5_000_000_000
    )

    assert (
        policy.health.on_timeout
        == "stop_execution"
    )

    assert (
        policy.limits.memory_limit_mb
        == 512
    )

    assert policy.limits.cpu_limit == 1.5

    assert (
        policy.limits.max_message_bytes
        == 8 * 1024 * 1024
    )


def test_explicit_parameters_override_execution_defaults_recursively():
    defaults = {
        "model": {
            "device": "cpu",
            "batch": 1,
        },
        "workers": 2,
    }

    explicit = {
        "model": {
            "batch": 4,
        },
        "workers": 8,
    }

    resolved = merge_node_parameters(
        defaults,
        explicit,
    )

    assert resolved == {
        "model": {
            "device": "cpu",
            "batch": 4,
        },
        "workers": 8,
    }

    assert defaults[
        "model"
    ][
        "batch"
    ] == 1


@pytest.mark.parametrize(
    "field",
    [
        "target",
        "backend",
        "uses",
        "inputs",
        "outputs",
    ],
)
def test_execution_context_cannot_change_node_topology(
    field,
):
    with pytest.raises(
        NodeExecutionResolutionError,
        match="unsupported fields",
    ):
        resolve_node_execution_defaults(
            {
                field: {},
            }
        )


def test_execution_context_resources_are_execution_limits_not_bindings():
    parameters, policy = (
        resolve_node_execution_defaults(
            {
                "resources": {
                    "memory_limit_mb": 128,
                    "cpu_limit": 0.75,
                    "max_message_bytes": (
                        4 * 1024 * 1024
                    ),
                },
            }
        )
    )

    assert parameters == {}

    assert (
        policy.limits.memory_limit_mb
        == 128
    )

    assert (
        policy.limits.cpu_limit
        == 0.75
    )

    assert (
        policy.limits.max_message_bytes
        == 4 * 1024 * 1024
    )

    assert not hasattr(
        policy,
        "resource_bindings",
    )


def test_unknown_nested_execution_field_is_rejected():
    with pytest.raises(
        NodeExecutionResolutionError,
        match="unsupported fields",
    ):
        resolve_node_execution_defaults(
            {
                "execution": {
                    "magic": True,
                },
            }
        )


def test_invalid_duration_is_rejected_before_runtime():
    with pytest.raises(
        NodeExecutionResolutionError,
        match="finite non-negative",
    ):
        resolve_node_execution_defaults(
            {
                "health": {
                    "timeout_ms": -1,
                },
            }
        )


def test_fallback_node_requires_explicit_fallback_uses():
    with pytest.raises(
        ValueError,
        match="fallback_node requires",
    ):
        resolve_node_execution_defaults(
            {
                "failure": {
                    "policy": (
                        "fallback_node"
                    ),
                },
            }
        )


def test_canonical_node_execution_module_has_no_legacy_runtime_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "node_execution.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8",
        ),
        filename=str(path),
    )

    forbidden_modules = {
        "manifest",
        "manifest_model",
        "runtime_components",
        "runtime_primitives",
        "runtime_workers",
        "hybrid_runtime",
        "local_backend",
        "compatibility",
    }

    forbidden_names = {
        "NodeConfig",
        "RuntimeNodeBinding",
        "PipelineManifest",
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
