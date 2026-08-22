from __future__ import annotations

import ast
from dataclasses import (
    FrozenInstanceError,
    MISSING,
    fields,
)
from pathlib import Path

import pytest

from nodrix.runtime_primitives import (
    RuntimeNodeBinding,
)


def _binding() -> RuntimeNodeBinding:
    return RuntimeNodeBinding(
        uses="tests.node",
        parameters={
            "threshold": 0.5,
        },
        resource_bindings={
            "camera": "front_camera",
        },
        synchronization_policy="approximate_timestamp",
        synchronization_tolerance_ns=12_500_000,
        synchronization_trigger_port="image",
        synchronization_optional_inputs=(
            "imu",
        ),
        failure_policy="restart_node",
        fallback_uses=None,
        failure_max_restarts=3,
        failure_backoff_ms=250,
        health_timeout_ns=750_000_000,
        health_on_timeout="restart",
        max_message_bytes=4096,
        memory_limit_mb=256,
        cpu_limit=1.5,
        isolation="process",
        cpu_affinity=(
            2,
            3,
        ),
        device="cpu",
        memory_inputs={
            "image": {
                "domain": "cpu",
            },
        },
        memory_outputs={
            "result": {
                "domain": "cpu",
            },
        },
    )


def test_runtime_node_binding_has_no_hidden_defaults():
    for definition in fields(
        RuntimeNodeBinding
    ):
        assert (
            definition.default
            is MISSING
        )
        assert (
            definition.default_factory
            is MISSING
        )


def test_runtime_node_binding_preserves_resolved_values():
    binding = _binding()

    assert (
        binding.uses
        == "tests.node"
    )

    assert (
        binding.synchronization_tolerance_ns
        == 12_500_000
    )

    assert (
        binding.health_timeout_ns
        == 750_000_000
    )

    assert (
        binding.cpu_affinity
        == (2, 3)
    )

    assert (
        binding.parameters[
            "threshold"
        ]
        == 0.5
    )


def test_runtime_node_binding_is_immutable():
    binding = _binding()

    with pytest.raises(
        FrozenInstanceError,
    ):
        binding.device = "gpu"

    with pytest.raises(
        TypeError,
    ):
        binding.parameters[
            "other"
        ] = 1

    with pytest.raises(
        TypeError,
    ):
        binding.resource_bindings[
            "other"
        ] = "resource"

    with pytest.raises(
        TypeError,
    ):
        binding.memory_inputs[
            "other"
        ] = {}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "uses",
            "",
        ),
        (
            "synchronization_tolerance_ns",
            -1,
        ),
        (
            "failure_max_restarts",
            -1,
        ),
        (
            "failure_backoff_ms",
            -1,
        ),
        (
            "health_timeout_ns",
            -1,
        ),
        (
            "max_message_bytes",
            0,
        ),
        (
            "memory_limit_mb",
            0,
        ),
        (
            "cpu_limit",
            0,
        ),
    ],
)
def test_runtime_node_binding_rejects_invalid_mechanics(
    field,
    value,
):
    values = {
        definition.name: getattr(
            _binding(),
            definition.name,
        )
        for definition in fields(
            RuntimeNodeBinding
        )
    }

    values[
        field
    ] = value

    with pytest.raises(
        ValueError,
    ):
        RuntimeNodeBinding(
            **values
        )


def test_runtime_node_binding_module_has_no_description_model_import():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_primitives.py"
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
        "hybrid_runtime",
        "compatibility",
        "planning",
    }

    forbidden_names = {
        "NodeConfig",
        "PipelineManifest",
        "SystemModel",
        "SystemExecutionPlan",
        "PlannedNode",
    }

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.ImportFrom,
        ):
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
