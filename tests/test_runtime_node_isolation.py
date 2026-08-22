from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nodrix.errors import RuntimeGraphError
from nodrix.node import Node, SourceNode
from nodrix import runtime_node_isolation
from nodrix.runtime_node_isolation import (
    RuntimeProcessIsolationSettings,
    materialize_runtime_node_isolation,
)
from nodrix.runtime_primitives import (
    RuntimeNodeBinding,
)


class _Processor(Node):
    input_types = {
        "input": "core.object",
    }

    output_types = {
        "output": "core.object",
    }

    input_memory = {
        "input": {
            "domain": "host",
        },
    }

    output_memory = {
        "output": {
            "domain": "shared",
        },
    }

    optional_inputs = frozenset()


class _Source(SourceNode):
    output_types = {
        "output": "core.object",
    }


class _ProxyProbe:
    def __init__(
        self,
        **kwargs,
    ):
        self.kwargs = kwargs


def _binding(
    *,
    isolation="process",
):
    return RuntimeNodeBinding(
        uses="demo.worker",
        parameters={
            "workers": 4,
        },
        resource_bindings={},
        synchronization_policy=(
            "exact_sequence"
        ),
        synchronization_tolerance_ns=(
            20_000_000
        ),
        synchronization_trigger_port=None,
        synchronization_optional_inputs=(),
        failure_policy="restart_node",
        fallback_uses=None,
        failure_max_restarts=7,
        failure_backoff_ms=125,
        health_timeout_ns=0,
        health_on_timeout="report",
        max_message_bytes=(
            32 * 1024 * 1024
        ),
        memory_limit_mb=512,
        cpu_limit=1.5,
        isolation=isolation,
        cpu_affinity=(
            2,
            3,
        ),
        device="cpu",
        memory_inputs={},
        memory_outputs={},
    )


def _settings(
    tmp_path,
):
    return RuntimeProcessIsolationSettings(
        base_dir=tmp_path,
        input_block_size=(
            8 * 1024 * 1024
        ),
        input_capacity=8,
        output_block_size=(
            16 * 1024 * 1024
        ),
        output_capacity=4,
        threshold=4096,
    )


def test_in_process_isolation_preserves_node_identity(
    tmp_path,
):
    node = _Processor({})

    actual = (
        materialize_runtime_node_isolation(
            name="worker",
            node=node,
            binding=_binding(
                isolation="in_process",
            ),
            settings=_settings(
                tmp_path
            ),
        )
    )

    assert actual is node


def test_process_isolation_maps_binding_and_engine_settings(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        runtime_node_isolation,
        "ProcessNodeProxy",
        _ProxyProbe,
    )

    node = _Processor({})

    actual = (
        materialize_runtime_node_isolation(
            name="worker",
            node=node,
            binding=_binding(),
            settings=_settings(
                tmp_path
            ),
        )
    )

    assert isinstance(
        actual,
        _ProxyProbe,
    )

    kwargs = actual.kwargs

    assert kwargs["name"] == "worker"
    assert kwargs["uses"] == "demo.worker"
    assert kwargs["base_dir"] == tmp_path

    assert kwargs["parameters"] == {
        "workers": 4,
    }

    assert kwargs["input_types"] == {
        "input": "core.object",
    }

    assert kwargs["output_types"] == {
        "output": "core.object",
    }

    assert kwargs["input_memory"] == {
        "input": {
            "domain": "host",
        },
    }

    assert kwargs["output_memory"] == {
        "output": {
            "domain": "shared",
        },
    }

    assert kwargs["block_size"] == (
        8 * 1024 * 1024
    )

    assert kwargs["capacity"] == 8

    assert kwargs["output_block_size"] == (
        16 * 1024 * 1024
    )

    assert kwargs["output_capacity"] == 4
    assert kwargs["threshold"] == 4096

    assert (
        kwargs["failure_policy"]
        == "restart_node"
    )

    assert kwargs["max_restarts"] == 7
    assert kwargs["backoff_ms"] == 125

    assert kwargs["cpu_affinity"] == [
        2,
        3,
    ]

    assert kwargs["device"] == "cpu"

    assert kwargs["max_message_bytes"] == (
        32 * 1024 * 1024
    )

    assert kwargs["memory_limit_mb"] == 512
    assert kwargs["cpu_limit"] == 1.5


def test_process_source_uses_source_proxy(
    monkeypatch,
    tmp_path,
):
    class SourceProxyProbe(
        _ProxyProbe
    ):
        pass

    class ProcessorProxyProbe(
        _ProxyProbe
    ):
        pass

    monkeypatch.setattr(
        runtime_node_isolation,
        "ProcessSourceProxy",
        SourceProxyProbe,
    )

    monkeypatch.setattr(
        runtime_node_isolation,
        "ProcessNodeProxy",
        ProcessorProxyProbe,
    )

    actual = (
        materialize_runtime_node_isolation(
            name="source",
            node=_Source({}),
            binding=_binding(),
            settings=_settings(
                tmp_path
            ),
        )
    )

    assert isinstance(
        actual,
        SourceProxyProbe,
    )

    assert not isinstance(
        actual,
        ProcessorProxyProbe,
    )


def test_unknown_isolation_mode_fails_explicitly(
    tmp_path,
):
    binding = _binding()

    object.__setattr__(
        binding,
        "isolation",
        "mystery",
    )

    with pytest.raises(
        RuntimeGraphError,
        match="unsupported isolation mode",
    ):
        materialize_runtime_node_isolation(
            name="worker",
            node=_Processor({}),
            binding=binding,
            settings=_settings(
                tmp_path
            ),
        )


def test_process_isolation_module_has_no_manifest_or_system_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_node_isolation.py"
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


def test_runtime_builder_uses_shared_process_isolation_boundary():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_builder.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    assert (
        "RuntimeProcessIsolationSettings("
        in source
    )

    assert (
        "materialize_runtime_node_isolation("
        in source
    )

    assert (
        "ProcessSourceProxy("
        not in source
    )

    assert (
        "proxy_cls ="
        not in source
    )

    assert (
        "block_size=shared."
        not in source
    )

    assert (
        "failure_policy=binding."
        not in source
    )
