from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from nodrix.system.direct_materialization import (
    DirectMaterializationError,
    materialize_direct_context,
)


@dataclass(frozen=True)
class _Named:
    name: str


@dataclass(frozen=True)
class _Node:
    id: str


@dataclass(frozen=True)
class _Connection:
    identity: str


class _ContextProbe:
    def __init__(self) -> None:
        self.target = _Named("host")
        self.resource = _Named("camera")
        self.application = _Named("driver")

        self.node_a = _Node("main/source")
        self.node_b = _Node("main/sink")

        self.connection = _Connection(
            "main/source.out->main/sink.in"
        )

        self.targets = (
            self.target,
        )
        self.resources = (
            self.resource,
        )
        self.applications = (
            self.application,
        )
        self.nodes = (
            self.node_a,
            self.node_b,
        )

    def graph_names(self):
        return ("main",)

    def nodes_for_graph(self, graph):
        assert graph == "main"
        return (
            self.node_a,
            self.node_b,
        )

    def connections_for_graph(self, graph):
        assert graph == "main"
        return (
            self.connection,
        )


def test_materialization_preserves_canonical_object_identity():
    context = _ContextProbe()

    materialized = materialize_direct_context(
        context,
    )

    assert materialized.context is context

    assert (
        materialized.targets_by_name["host"]
        is context.target
    )

    assert (
        materialized.resources_by_name["camera"]
        is context.resource
    )

    assert (
        materialized.applications_by_name["driver"]
        is context.application
    )

    assert (
        materialized.nodes_by_id["main/source"]
        is context.node_a
    )

    assert (
        materialized.nodes_by_graph["main"][0]
        is context.node_a
    )

    assert (
        materialized.connections_by_graph["main"][0]
        is context.connection
    )


def test_materialization_indexes_are_immutable():
    materialized = materialize_direct_context(
        _ContextProbe(),
    )

    with pytest.raises(TypeError):
        materialized.nodes_by_id["other"] = _Node(
            "other"
        )

    with pytest.raises(TypeError):
        materialized.resources_by_name["other"] = _Named(
            "other"
        )


def test_materialization_rejects_duplicate_runtime_identity():
    context = _ContextProbe()

    context.nodes = (
        _Node("main/duplicate"),
        _Node("main/duplicate"),
    )

    with pytest.raises(
        DirectMaterializationError,
        match="duplicate node identity",
    ):
        materialize_direct_context(
            context,
        )


def test_materialization_does_not_flatten_graph_node_names():
    context = _ContextProbe()

    context.node_a = _Node("left/worker")
    context.node_b = _Node("right/worker")

    context.nodes = (
        context.node_a,
        context.node_b,
    )

    def graph_names():
        return (
            "left",
            "right",
        )

    def nodes_for_graph(graph):
        if graph == "left":
            return (context.node_a,)
        if graph == "right":
            return (context.node_b,)
        raise AssertionError(graph)

    def connections_for_graph(graph):
        assert graph in {
            "left",
            "right",
        }
        return ()

    context.graph_names = graph_names
    context.nodes_for_graph = nodes_for_graph
    context.connections_for_graph = connections_for_graph

    materialized = materialize_direct_context(
        context,
    )

    assert set(materialized.nodes_by_id) == {
        "left/worker",
        "right/worker",
    }

    assert (
        materialized.nodes_by_graph["left"][0]
        is context.node_a
    )

    assert (
        materialized.nodes_by_graph["right"][0]
        is context.node_b
    )


def test_direct_materializer_has_no_legacy_semantic_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_materialization.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )
    tree = ast.parse(
        source,
        filename=str(path),
    )

    forbidden_import_names = {
        "PipelineManifest",
        "SystemModel",
        "SystemExecutionPlan",
    }

    forbidden_modules = {
        "manifest",
        "hybrid_runtime",
        "compatibility",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert (
                    alias.name.split(".")[-1]
                    not in forbidden_modules
                )

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""

            assert (
                module.split(".")[-1]
                not in forbidden_modules
            )

            for alias in node.names:
                assert (
                    alias.name
                    not in forbidden_import_names
                )


def test_direct_materializer_does_not_copy_planned_parameters():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_materialization.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )
    tree = ast.parse(
        source,
        filename=str(path),
    )

    forbidden_calls = {
        "asdict",
        "model_dump",
        "model_validate",
    }

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        function = node.func

        if isinstance(function, ast.Name):
            assert function.id not in forbidden_calls

        elif isinstance(function, ast.Attribute):
            assert function.attr not in forbidden_calls


def test_materializer_contains_no_node_alias_layer():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_materialization.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    assert "_node_aliases" not in source
    assert "node_aliases" not in source
