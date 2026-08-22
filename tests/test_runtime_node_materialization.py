from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nodrix.errors import RuntimeGraphError
from nodrix.node import Node
from nodrix.runtime_node_materialization import (
    load_runtime_fallback_node,
    validate_runtime_node_materialization,
    validate_runtime_node_parameters,
)
from nodrix.runtime_primitives import (
    RuntimeNodeBinding,
)


class _Primary(Node):
    input_types = {
        "input": "core.object",
        "side": "core.object",
    }

    output_types = {
        "output": "core.object",
    }

    optional_inputs = frozenset(
        {
            "side",
        }
    )


class _Fallback(_Primary):
    pass


def _binding(
    *,
    failure_policy="stop_execution",
    fallback_uses=None,
    isolation="in_process",
    trigger_port=None,
    optional_inputs=(),
):
    return RuntimeNodeBinding(
        uses="demo.primary",
        parameters={
            "workers": 2,
        },
        resource_bindings={},
        synchronization_policy=(
            "exact_sequence"
        ),
        synchronization_tolerance_ns=(
            20_000_000
        ),
        synchronization_trigger_port=(
            trigger_port
        ),
        synchronization_optional_inputs=(
            optional_inputs
        ),
        failure_policy=failure_policy,
        fallback_uses=fallback_uses,
        failure_max_restarts=3,
        failure_backoff_ms=250,
        health_timeout_ns=0,
        health_on_timeout="report",
        max_message_bytes=(
            256 * 1024 * 1024
        ),
        memory_limit_mb=None,
        cpu_limit=None,
        isolation=isolation,
        cpu_affinity=(),
        device="auto",
        memory_inputs={},
        memory_outputs={},
    )


def test_primary_contract_validation_accepts_resolved_binding(
    monkeypatch,
    tmp_path,
):
    calls = []

    monkeypatch.setattr(
        "nodrix.runtime_node_materialization.validate_parameters",
        lambda uses, parameters: (
            calls.append(
                (
                    uses,
                    parameters,
                )
            )
        ),
    )

    binding = _binding(
        trigger_port="input",
        optional_inputs=(
            "side",
        ),
    )

    validate_runtime_node_parameters(
        binding
    )

    validate_runtime_node_materialization(
        name="worker",
        node=_Primary({}),
        binding=binding,
        declared_inputs={
            "input": "core.object",
            "side": "core.object",
        },
        declared_outputs={
            "output": "core.object",
        },
        base_dir=tmp_path,
    )

    assert calls == [
        (
            "demo.primary",
            {
                "workers": 2,
            },
        ),
    ]


def test_declared_input_mismatch_is_rejected(
    tmp_path,
):
    with pytest.raises(
        RuntimeGraphError,
        match="declared inputs",
    ):
        validate_runtime_node_materialization(
            name="worker",
            node=_Primary({}),
            binding=_binding(),
            declared_inputs={
                "wrong": "core.object",
            },
            declared_outputs={},
            base_dir=tmp_path,
        )


def test_declared_output_mismatch_is_rejected(
    tmp_path,
):
    with pytest.raises(
        RuntimeGraphError,
        match="declared outputs",
    ):
        validate_runtime_node_materialization(
            name="worker",
            node=_Primary({}),
            binding=_binding(),
            declared_inputs={},
            declared_outputs={
                "wrong": "core.object",
            },
            base_dir=tmp_path,
        )


def test_unknown_trigger_port_is_rejected(
    tmp_path,
):
    with pytest.raises(
        RuntimeGraphError,
        match="trigger_port",
    ):
        validate_runtime_node_materialization(
            name="worker",
            node=_Primary({}),
            binding=_binding(
                trigger_port="missing",
            ),
            declared_inputs={},
            declared_outputs={},
            base_dir=tmp_path,
        )


def test_required_input_cannot_be_configured_optional(
    tmp_path,
):
    with pytest.raises(
        RuntimeGraphError,
        match="cannot make required inputs optional",
    ):
        validate_runtime_node_materialization(
            name="worker",
            node=_Primary({}),
            binding=_binding(
                optional_inputs=(
                    "input",
                ),
            ),
            declared_inputs={},
            declared_outputs={},
            base_dir=tmp_path,
        )


def test_fallback_loading_is_shared_and_contract_checked(
    monkeypatch,
    tmp_path,
):
    calls = []

    monkeypatch.setattr(
        "nodrix.runtime_node_materialization.validate_parameters",
        lambda uses, parameters: (
            calls.append(
                (
                    uses,
                    parameters,
                )
            )
        ),
    )

    monkeypatch.setattr(
        "nodrix.runtime_node_materialization.load_runtime_node",
        lambda uses, parameters, *, base_dir: (
            _Fallback(
                parameters
            )
        ),
    )

    binding = _binding(
        failure_policy="fallback_node",
        fallback_uses="demo.fallback",
    )

    fallback = load_runtime_fallback_node(
        name="worker",
        primary=_Primary({}),
        binding=binding,
        base_dir=tmp_path,
    )

    assert isinstance(
        fallback,
        _Fallback,
    )

    assert calls == [
        (
            "demo.fallback",
            {
                "workers": 2,
            },
        ),
    ]


def test_fallback_requires_in_process_isolation(
    tmp_path,
):
    binding = _binding(
        failure_policy="fallback_node",
        fallback_uses="demo.fallback",
        isolation="process",
    )

    with pytest.raises(
        RuntimeGraphError,
        match="requires in_process",
    ):
        load_runtime_fallback_node(
            name="worker",
            primary=_Primary({}),
            binding=binding,
            base_dir=tmp_path,
        )


def test_shared_materialization_has_no_manifest_or_system_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_node_materialization.py"
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
        "runtime_builder",
        "runtime_workers",
        "hybrid_runtime",
        "planning",
        "execution_context",
        "node_execution",
        "local_backend",
        "compatibility",
    }

    forbidden_names = {
        "NodeConfig",
        "PipelineManifest",
        "PlannedNode",
        "SystemExecutionContext",
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
