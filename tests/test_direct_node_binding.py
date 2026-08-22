from __future__ import annotations

import ast
from pathlib import Path

from nodrix.runtime_primitives import (
    RuntimeNodeBinding,
)
from nodrix.system.direct_node_materialization import (
    runtime_node_binding_from_planned,
)
from nodrix.system.node_execution import (
    ResolvedNodeExecutionPlacement,
    ResolvedNodeExecutionPolicy,
    ResolvedNodeFailurePolicy,
    ResolvedNodeHealthPolicy,
    ResolvedNodeMemoryPolicy,
    ResolvedNodeResourceLimits,
    ResolvedNodeSynchronization,
)
from nodrix.system.planning import PlannedNode


def _planned_node() -> PlannedNode:
    return PlannedNode(
        ordinal=0,
        id="main/worker",
        graph="main",
        name="worker",
        uses="demo.worker",
        target="local",
        backend="local",
        parameters={
            "workers": 4,
            "nested": {
                "batch": 2,
            },
        },
        resources={
            "camera": "front-camera",
        },
        inputs={
            "image": "image/rgb8",
            "detections": "detections/v1",
        },
        outputs={
            "result": "detections/v1",
        },
        optional_inputs=(
            "detections",
        ),
        execution=ResolvedNodeExecutionPolicy(
            synchronization=(
                ResolvedNodeSynchronization(
                    policy=(
                        "approximate_timestamp"
                    ),
                    tolerance_ns=12_000_000,
                    trigger_port="image",
                    optional_inputs=(
                        "detections",
                    ),
                )
            ),
            execution=(
                ResolvedNodeExecutionPlacement(
                    isolation="process",
                    cpu_affinity=(
                        2,
                        3,
                    ),
                    device="cpu",
                )
            ),
            failure=(
                ResolvedNodeFailurePolicy(
                    policy="fallback_node",
                    max_restarts=5,
                    backoff_ms=125,
                    fallback_uses=(
                        "demo.worker_fallback"
                    ),
                )
            ),
            health=(
                ResolvedNodeHealthPolicy(
                    timeout_ns=(
                        3_000_000_000
                    ),
                    on_timeout="restart_node",
                )
            ),
            limits=(
                ResolvedNodeResourceLimits(
                    memory_limit_mb=256,
                    cpu_limit=1.5,
                    max_message_bytes=(
                        16 * 1024 * 1024
                    ),
                )
            ),
            memory=(
                ResolvedNodeMemoryPolicy(
                    inputs={
                        "image": {
                            "type": "host",
                        },
                    },
                    outputs={
                        "result": {
                            "type": "shared",
                        },
                    },
                )
            ),
        ),
        metadata={
            "label": "worker",
        },
        extensions={
            "legacy": {
                "failure": {
                    "policy": "stop_pipeline",
                },
            },
        },
    )


def test_planned_node_maps_exactly_to_runtime_binding():
    planned = _planned_node()

    binding = (
        runtime_node_binding_from_planned(
            planned
        )
    )

    assert isinstance(
        binding,
        RuntimeNodeBinding,
    )

    assert binding.uses == planned.uses

    assert dict(
        binding.parameters
    ) == planned.parameters

    assert dict(
        binding.resource_bindings
    ) == planned.resources

    assert (
        binding.synchronization_policy
        == "approximate_timestamp"
    )

    assert (
        binding.synchronization_tolerance_ns
        == 12_000_000
    )

    assert (
        binding.synchronization_trigger_port
        == "image"
    )

    assert (
        binding.synchronization_optional_inputs
        == (
            "detections",
        )
    )

    assert (
        binding.failure_policy
        == "fallback_node"
    )

    assert (
        binding.fallback_uses
        == "demo.worker_fallback"
    )

    assert (
        binding.failure_max_restarts
        == 5
    )

    assert (
        binding.failure_backoff_ms
        == 125
    )

    assert (
        binding.health_timeout_ns
        == 3_000_000_000
    )

    assert (
        binding.health_on_timeout
        == "restart_node"
    )

    assert (
        binding.max_message_bytes
        == 16 * 1024 * 1024
    )

    assert (
        binding.memory_limit_mb
        == 256
    )

    assert binding.cpu_limit == 1.5

    assert binding.isolation == "process"

    assert binding.cpu_affinity == (
        2,
        3,
    )

    assert binding.device == "cpu"

    assert dict(
        binding.memory_inputs
    ) == {
        "image": {
            "type": "host",
        },
    }

    assert dict(
        binding.memory_outputs
    ) == {
        "result": {
            "type": "shared",
        },
    }


def test_default_planned_policy_maps_without_runtime_defaults():
    planned = PlannedNode(
        ordinal=0,
        id="main/worker",
        graph="main",
        name="worker",
        uses="demo.worker",
        target="local",
        backend="local",
    )

    binding = (
        runtime_node_binding_from_planned(
            planned
        )
    )

    policy = planned.execution

    assert (
        binding.synchronization_policy
        == policy.synchronization.policy
    )

    assert (
        binding.synchronization_tolerance_ns
        == policy.synchronization.tolerance_ns
    )

    assert (
        binding.failure_policy
        == policy.failure.policy
    )

    assert (
        binding.health_timeout_ns
        == policy.health.timeout_ns
    )

    assert (
        binding.max_message_bytes
        == policy.limits.max_message_bytes
    )

    assert (
        binding.isolation
        == policy.execution.isolation
    )

    assert (
        binding.device
        == policy.execution.device
    )


def test_direct_node_binding_does_not_read_legacy_extensions():
    planned = _planned_node()

    binding = (
        runtime_node_binding_from_planned(
            planned
        )
    )

    assert (
        binding.failure_policy
        == "fallback_node"
    )

    assert (
        binding.failure_policy
        != "stop_pipeline"
    )


def test_direct_node_adapter_does_not_use_definition_port_contracts():
    planned = _planned_node()

    binding = (
        runtime_node_binding_from_planned(
            planned
        )
    )

    assert not hasattr(
        binding,
        "inputs",
    )

    assert not hasattr(
        binding,
        "outputs",
    )

    assert (
        planned.optional_inputs
        == (
            "detections",
        )
    )

    assert (
        binding.synchronization_optional_inputs
        == planned.execution
        .synchronization
        .optional_inputs
    )


def test_direct_node_module_has_no_legacy_or_execution_context_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_node_materialization.py"
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
        "execution_context",
    }

    forbidden_names = {
        "NodeConfig",
        "PipelineManifest",
        "HybridPipelineRuntime",
        "SystemExecutionContext",
    }

    for node in ast.walk(tree):
        if isinstance(
            node,
            ast.Attribute,
        ):
            assert (
                node.attr
                != "extensions"
            )

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
