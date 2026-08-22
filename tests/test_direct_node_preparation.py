from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nodrix.node import Node
from nodrix.system import (
    direct_node_preparation,
)
from nodrix.system.direct_environment import (
    DirectExecutionEnvironment,
)
from nodrix.system.direct_node_preparation import (
    DirectNodePreparationError,
    materialize_direct_node,
)
from nodrix.system.node_execution import (
    ResolvedNodeExecutionPlacement,
    ResolvedNodeExecutionPolicy,
)
from nodrix.system.planning import (
    PlannedNode,
)


class _Processor(Node):
    input_types = {
        "input": "core.object",
    }

    output_types = {
        "output": "core.object",
    }


def _planned(
    *,
    isolation: str = "in_process",
) -> PlannedNode:
    return PlannedNode(
        ordinal=0,
        id="main.worker",
        graph="main",
        name="worker",
        uses="demo.worker",
        target="local",
        backend="local",
        parameters={
            "workers": 2,
        },
        resources={},
        inputs={
            "input": "core.object",
        },
        outputs={
            "output": "core.object",
        },
        execution=(
            ResolvedNodeExecutionPolicy(
                execution=(
                    ResolvedNodeExecutionPlacement(
                        isolation=isolation,
                    )
                )
            )
        ),
    )


def test_direct_in_process_node_materializes_loaded_node(
    monkeypatch,
    tmp_path,
):
    planned = _planned()

    calls = {}

    def validate_parameters(
        binding,
    ):
        calls[
            "validated_uses"
        ] = binding.uses

    def load(
        uses,
        parameters,
        *,
        base_dir,
    ):
        calls["uses"] = uses
        calls["parameters"] = parameters
        calls["base_dir"] = base_dir

        return _Processor(
            parameters
        )

    monkeypatch.setattr(
        direct_node_preparation,
        "validate_runtime_node_parameters",
        validate_parameters,
    )

    monkeypatch.setattr(
        direct_node_preparation,
        "load_runtime_node",
        load,
    )

    environment = (
        DirectExecutionEnvironment(
            base_dir=tmp_path,
        )
    )

    loaded = materialize_direct_node(
        planned,
        environment=environment,
    )

    assert loaded.name == "main.worker"

    assert loaded.binding.uses == (
        "demo.worker"
    )

    assert loaded.binding.isolation == (
        "in_process"
    )

    assert isinstance(
        loaded.node,
        _Processor,
    )

    assert loaded.stats is None

    assert calls[
        "validated_uses"
    ] == "demo.worker"

    assert calls["uses"] == "demo.worker"

    assert calls["parameters"] == {
        "workers": 2,
    }

    assert (
        calls["base_dir"]
        == tmp_path.resolve()
    )


def test_process_node_is_rejected_before_loading(
    monkeypatch,
    tmp_path,
):
    planned = _planned(
        isolation="process",
    )

    def unexpected_load(
        *args,
        **kwargs,
    ):
        raise AssertionError(
            "process implementation must not "
            "be loaded before canonical "
            "process-memory policy exists"
        )

    monkeypatch.setattr(
        direct_node_preparation,
        "load_runtime_node",
        unexpected_load,
    )

    with pytest.raises(
        DirectNodePreparationError,
        match=(
            "canonical process-memory "
            "settings"
        ),
    ) as captured:
        materialize_direct_node(
            planned,
            environment=(
                DirectExecutionEnvironment(
                    base_dir=tmp_path,
                )
            ),
        )

    assert (
        captured.value.node_id
        == "main.worker"
    )


def test_direct_node_uses_canonical_id_not_graph_local_name(
    monkeypatch,
    tmp_path,
):
    planned = _planned()

    monkeypatch.setattr(
        direct_node_preparation,
        "validate_runtime_node_parameters",
        lambda binding: None,
    )

    monkeypatch.setattr(
        direct_node_preparation,
        "load_runtime_node",
        lambda uses, parameters, *, base_dir: (
            _Processor(
                parameters
            )
        ),
    )

    loaded = materialize_direct_node(
        planned,
        environment=(
            DirectExecutionEnvironment(
                base_dir=tmp_path,
            )
        ),
    )

    assert planned.name == "worker"

    assert planned.id == "main.worker"

    assert loaded.name == planned.id


def test_direct_node_preparation_has_no_legacy_or_execution_context_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_node_preparation.py"
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
        "PipelineManifest",
        "NodeConfig",
        "RuntimeConfig",
        "HybridPipelineRuntime",
        "SystemExecutionContext",
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


def test_direct_node_preparation_has_no_graph_or_lifecycle_materialization():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_node_preparation.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    forbidden = {
        "EdgeQueue",
        "RuntimeEdgeQueue",
        "plan_memory",
        ".configure(",
        ".start(",
        ".stop(",
        "ProcessNodeProxy",
        "ProcessSourceProxy",
    }

    for token in forbidden:
        assert token not in source


def test_direct_preparation_requires_environment_when_nodes_exist(
    monkeypatch,
):
    from types import SimpleNamespace

    from nodrix.system import (
        direct_preparation,
    )

    planned = _planned()

    context = SimpleNamespace(
        backend="local",
        resources=(),
        applications=(),
        nodes=(
            planned,
        ),
        execution_context=None,
    )

    monkeypatch.setattr(
        direct_preparation,
        "materialize_direct_context",
        lambda value: (
            SimpleNamespace(
                context=value,
            )
        ),
    )

    with pytest.raises(
        DirectNodePreparationError,
        match="DirectExecutionEnvironment",
    ):
        direct_preparation.prepare_direct_execution(
            context
        )


def test_direct_preparation_materializes_nodes_by_canonical_id(
    monkeypatch,
    tmp_path,
):
    from types import SimpleNamespace

    from nodrix.system import (
        direct_preparation,
    )

    planned = _planned()

    context = SimpleNamespace(
        backend="local",
        resources=(),
        applications=(),
        nodes=(
            planned,
        ),
        execution_context=None,
    )

    monkeypatch.setattr(
        direct_preparation,
        "materialize_direct_context",
        lambda value: (
            SimpleNamespace(
                context=value,
            )
        ),
    )

    sentinel = object()

    calls = []

    def materialize_node(
        value,
        *,
        environment,
        mechanics,
    ):
        calls.append(
            (
                value,
                environment,
                mechanics,
            )
        )

        return sentinel

    monkeypatch.setattr(
        direct_preparation,
        "materialize_direct_node",
        materialize_node,
    )

    environment = (
        DirectExecutionEnvironment(
            base_dir=tmp_path,
        )
    )

    prepared = (
        direct_preparation
        .prepare_direct_execution(
            context,
            environment=environment,
        )
    )

    assert dict(
        prepared.payload.nodes
    ) == {
        "main.worker": sentinel,
    }

    assert calls == [
        (
            planned,
            environment,
            prepared.payload.mechanics,
        ),
    ]


def test_direct_prepared_nodes_mapping_is_immutable(
    monkeypatch,
    tmp_path,
):
    from types import SimpleNamespace

    from nodrix.system import (
        direct_preparation,
    )

    context = SimpleNamespace(
        backend="local",
        resources=(),
        applications=(),
        nodes=(),
        execution_context=None,
    )

    materialization = (
        SimpleNamespace(
            context=context,
        )
    )

    environment = (
        DirectExecutionEnvironment(
            base_dir=tmp_path,
        )
    )

    payload = (
        direct_preparation
        .DirectPreparedRuntime(
            materialization=materialization,
            resources={},
            applications={},
            nodes={
                "main.worker": object(),
            },
            environment=environment,
        )
    )

    with pytest.raises(
        TypeError,
    ):
        payload.nodes[
            "other"
        ] = object()


def _mechanics(
    *,
    telemetry=None,
    input_threshold=1024,
    output_threshold=1024,
):
    from nodrix.system.runtime_mechanics import (
        ResolvedProcessRuntimeMechanics,
        ResolvedRuntimeMechanics,
        ResolvedRuntimePoolMechanics,
    )

    return ResolvedRuntimeMechanics(
        telemetry_sample_capacity=telemetry,
        process=(
            ResolvedProcessRuntimeMechanics(
                input_pool=(
                    ResolvedRuntimePoolMechanics(
                        block_size=4 * 1024 * 1024,
                        capacity=11,
                        threshold=input_threshold,
                    )
                ),
                output_pool=(
                    ResolvedRuntimePoolMechanics(
                        block_size=2 * 1024 * 1024,
                        capacity=17,
                        threshold=output_threshold,
                    )
                ),
            )
        ),
    )


def test_direct_process_node_uses_resolved_runtime_mechanics(
    monkeypatch,
    tmp_path,
):
    planned = _planned(
        isolation="process",
    )

    primary = _Processor(
        {
            "workers": 2,
        }
    )

    isolated = _Processor(
        {
            "isolated": True,
        }
    )

    calls = {}

    monkeypatch.setattr(
        direct_node_preparation,
        "validate_runtime_node_parameters",
        lambda binding: None,
    )

    monkeypatch.setattr(
        direct_node_preparation,
        "load_runtime_node",
        lambda uses, parameters, *, base_dir: primary,
    )

    monkeypatch.setattr(
        direct_node_preparation,
        "validate_runtime_node_materialization",
        lambda **kwargs: None,
    )

    def isolate(
        *,
        name,
        node,
        binding,
        settings,
    ):
        calls["name"] = name
        calls["node"] = node
        calls["binding"] = binding
        calls["settings"] = settings

        return isolated

    monkeypatch.setattr(
        direct_node_preparation,
        "materialize_runtime_node_isolation",
        isolate,
    )

    environment = (
        DirectExecutionEnvironment(
            base_dir=tmp_path,
        )
    )

    loaded = materialize_direct_node(
        planned,
        environment=environment,
        mechanics=_mechanics(),
    )

    settings = calls["settings"]

    assert calls["name"] == planned.id
    assert calls["node"] is primary
    assert calls["binding"] is loaded.binding

    assert (
        settings.base_dir
        == tmp_path.resolve()
    )

    assert (
        settings.input_block_size
        == 4 * 1024 * 1024
    )

    assert settings.input_capacity == 11

    assert (
        settings.output_block_size
        == 2 * 1024 * 1024
    )

    assert settings.output_capacity == 17

    assert settings.threshold == 1024

    assert loaded.node is isolated
    assert loaded.stats is None


def test_direct_process_node_requires_canonical_process_mechanics(
    monkeypatch,
    tmp_path,
):
    from nodrix.system.runtime_mechanics import (
        ResolvedRuntimeMechanics,
    )

    planned = _planned(
        isolation="process",
    )

    monkeypatch.setattr(
        direct_node_preparation,
        "load_runtime_node",
        lambda *args, **kwargs: (
            pytest.fail(
                "node implementation must not load "
                "without process mechanics"
            )
        ),
    )

    with pytest.raises(
        DirectNodePreparationError,
        match="canonical process-memory settings",
    ):
        materialize_direct_node(
            planned,
            environment=(
                DirectExecutionEnvironment(
                    base_dir=tmp_path,
                )
            ),
            mechanics=(
                ResolvedRuntimeMechanics()
            ),
        )


def test_direct_process_node_rejects_unrepresentable_pool_thresholds(
    monkeypatch,
    tmp_path,
):
    planned = _planned(
        isolation="process",
    )

    monkeypatch.setattr(
        direct_node_preparation,
        "load_runtime_node",
        lambda *args, **kwargs: (
            pytest.fail(
                "node implementation must not load "
                "for unsupported process mechanics"
            )
        ),
    )

    with pytest.raises(
        DirectNodePreparationError,
        match="matching input_pool.threshold",
    ):
        materialize_direct_node(
            planned,
            environment=(
                DirectExecutionEnvironment(
                    base_dir=tmp_path,
                )
            ),
            mechanics=_mechanics(
                input_threshold=1024,
                output_threshold=2048,
            ),
        )


def test_direct_node_stats_use_only_explicit_canonical_capacity(
    monkeypatch,
    tmp_path,
):
    planned = _planned()

    monkeypatch.setattr(
        direct_node_preparation,
        "validate_runtime_node_parameters",
        lambda binding: None,
    )

    monkeypatch.setattr(
        direct_node_preparation,
        "load_runtime_node",
        lambda uses, parameters, *, base_dir: (
            _Processor(
                parameters
            )
        ),
    )

    loaded = materialize_direct_node(
        planned,
        environment=(
            DirectExecutionEnvironment(
                base_dir=tmp_path,
            )
        ),
        mechanics=_mechanics(
            telemetry=37,
        ),
    )

    assert loaded.stats is not None
    assert loaded.stats.sample_capacity == 37


def test_direct_node_preparation_uses_shared_process_materializer_only():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_node_preparation.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    assert (
        "materialize_runtime_node_isolation("
        in source
    )

    assert (
        "RuntimeProcessIsolationSettings("
        in source
    )

    assert "ProcessNodeProxy(" not in source
    assert "ProcessSourceProxy(" not in source
