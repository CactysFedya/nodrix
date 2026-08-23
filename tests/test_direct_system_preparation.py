from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import nodrix.system.direct_preparation as preparation
from nodrix.system.backend import (
    PreparedExecution,
)


def _context():
    resource_a = SimpleNamespace(
        name="resource-a",
    )

    resource_b = SimpleNamespace(
        name="resource-b",
    )

    application_a = SimpleNamespace(
        name="application-a",
    )

    return SimpleNamespace(
        backend="local",
        resources=(
            resource_a,
            resource_b,
        ),
        applications=(
            application_a,
        ),
        nodes=(),
        execution_context=None,
    )


def test_prepare_direct_execution_materializes_provider_state(
    monkeypatch,
):
    context = _context()

    direct_materialization = SimpleNamespace(
        context=context,
        nodes_by_graph={},
        connections_by_graph={},
    )

    calls = []

    resource_a = object()
    resource_b = object()
    application_a = object()

    monkeypatch.setattr(
        preparation,
        "materialize_direct_context",
        lambda value: (
            direct_materialization
        ),
    )

    def materialize_resource(
        planned,
    ):
        calls.append(
            (
                "resource",
                planned.name,
            )
        )

        return {
            "resource-a": resource_a,
            "resource-b": resource_b,
        }[
            planned.name
        ]

    def materialize_application(
        planned,
    ):
        calls.append(
            (
                "application",
                planned.name,
            )
        )

        assert planned.name == "application-a"

        return application_a

    monkeypatch.setattr(
        preparation,
        "materialize_direct_resource",
        materialize_resource,
    )

    monkeypatch.setattr(
        preparation,
        "materialize_direct_application",
        materialize_application,
    )

    prepared = (
        preparation.prepare_direct_execution(
            context
        )
    )

    assert isinstance(
        prepared,
        PreparedExecution,
    )

    assert prepared.backend == "local"
    assert prepared.context is context
    assert prepared.metadata == {}

    payload = prepared.payload

    assert isinstance(
        payload,
        preparation.DirectPreparedRuntime,
    )

    assert (
        payload.materialization
        is direct_materialization
    )

    assert payload.context is context

    assert tuple(
        payload.resources
    ) == (
        "resource-a",
        "resource-b",
    )

    assert tuple(
        payload.applications
    ) == (
        "application-a",
    )

    assert (
        payload.resources[
            "resource-a"
        ]
        is resource_a
    )

    assert (
        payload.resources[
            "resource-b"
        ]
        is resource_b
    )

    assert (
        payload.applications[
            "application-a"
        ]
        is application_a
    )

    assert calls == [
        (
            "resource",
            "resource-a",
        ),
        (
            "resource",
            "resource-b",
        ),
        (
            "application",
            "application-a",
        ),
    ]


def test_direct_prepared_runtime_indexes_are_immutable():
    context = _context()

    materialization = SimpleNamespace(
        context=context,
        nodes_by_graph={},
        connections_by_graph={},
    )

    payload = preparation.DirectPreparedRuntime(
        materialization=materialization,
        resources={
            "resource": object(),
        },
        applications={
            "application": object(),
        },
    )

    with pytest.raises(
        TypeError,
    ):
        payload.resources[
            "other"
        ] = object()

    with pytest.raises(
        TypeError,
    ):
        payload.applications[
            "other"
        ] = object()


def test_direct_preparation_does_not_run_provider_lifecycle(
    monkeypatch,
):
    context = _context()

    materialization = SimpleNamespace(
        context=context,
        nodes_by_graph={},
        connections_by_graph={},
    )

    class ProviderProbe:
        def __init__(self):
            self.opened = False
            self.configured = False
            self.started = False

        def open(self, context):
            self.opened = True

        def configure(self, context):
            self.configured = True

        def start(self):
            self.started = True

    resource_probe = ProviderProbe()
    application_probe = ProviderProbe()

    monkeypatch.setattr(
        preparation,
        "materialize_direct_context",
        lambda value: materialization,
    )

    monkeypatch.setattr(
        preparation,
        "materialize_direct_resource",
        lambda planned: resource_probe,
    )

    monkeypatch.setattr(
        preparation,
        "materialize_direct_application",
        lambda planned: application_probe,
    )

    preparation.prepare_direct_execution(
        context
    )

    assert resource_probe.opened is False

    assert (
        application_probe.configured
        is False
    )

    assert (
        application_probe.started
        is False
    )


def test_direct_preparation_has_no_legacy_execution_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_preparation.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8",
        ),
        filename=str(path),
    )

    forbidden_names = {
        "PipelineManifest",
        "NodeConfig",
        "ProviderResourceConfig",
        "ApplicationConfig",
        "HybridPipelineRuntime",
        "LocalPreparedPayload",
    }

    forbidden_modules = {
        "manifest",
        "manifest_model",
        "compatibility",
        "local_backend",
        "hybrid_runtime",
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


def test_direct_preparation_does_not_define_second_plan():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_preparation.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8",
        ),
        filename=str(path),
    )

    class_names = {
        node.name
        for node in tree.body
        if isinstance(
            node,
            ast.ClassDef,
        )
    }

    assert class_names == {
        "DirectPreparedRuntime",
    }

    assert not any(
        name.endswith("Plan")
        for name in class_names
    )
