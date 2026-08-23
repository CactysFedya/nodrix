from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nodrix.system.direct_environment import (
    DirectExecutionEnvironment,
)


def test_direct_execution_environment_preserves_absolute_base_dir(
    tmp_path,
):
    environment = (
        DirectExecutionEnvironment(
            base_dir=tmp_path,
        )
    )

    assert (
        environment.base_dir
        == tmp_path.resolve()
    )


def test_direct_execution_environment_rejects_relative_base_dir():
    with pytest.raises(
        ValueError,
        match="must be an absolute path",
    ):
        DirectExecutionEnvironment(
            base_dir=Path(
                "relative/project"
            ),
        )


def test_direct_execution_environment_is_frozen(
    tmp_path,
):
    environment = (
        DirectExecutionEnvironment(
            base_dir=tmp_path,
        )
    )

    with pytest.raises(
        AttributeError,
    ):
        environment.base_dir = (
            tmp_path / "other"
        )


def test_direct_environment_has_no_system_semantic_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_environment.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        source,
        filename=str(path),
    )

    forbidden_modules = {
        "planning",
        "model",
        "execution_context",
        "node_execution",
        "manifest",
        "manifest_model",
        "compatibility",
        "local_backend",
        "runtime_primitives",
        "runtime_node_isolation",
    }

    forbidden_names = {
        "SystemModel",
        "SystemExecutionPlan",
        "SystemExecutionContext",
        "PlannedNode",
        "RuntimeNodeBinding",
        "PipelineManifest",
        "RuntimeConfig",
        "RuntimeProcessIsolationSettings",
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


def test_direct_environment_does_not_define_runtime_policy():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_environment.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    forbidden = {
        "shared_pool",
        "process_output_pool",
        "telemetry_samples",
        "failure_policy",
        "node_defaults",
        "RuntimeConfig",
    }

    for token in forbidden:
        assert token not in source


def test_direct_preparation_preserves_backend_environment(
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

    materialization = SimpleNamespace(
        context=context,
        nodes_by_graph={},
        connections_by_graph={},
    )

    monkeypatch.setattr(
        direct_preparation,
        "materialize_direct_context",
        lambda value: (
            materialization
        ),
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

    assert (
        prepared.payload.environment
        is environment
    )

    assert (
        prepared.payload.environment
        .base_dir
        == tmp_path.resolve()
    )


def test_provider_only_direct_preparation_does_not_invent_environment(
    monkeypatch,
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

    materialization = SimpleNamespace(
        context=context,
        nodes_by_graph={},
        connections_by_graph={},
    )

    monkeypatch.setattr(
        direct_preparation,
        "materialize_direct_context",
        lambda value: (
            materialization
        ),
    )

    prepared = (
        direct_preparation
        .prepare_direct_execution(
            context
        )
    )

    assert (
        prepared.payload.environment
        is None
    )
