from __future__ import annotations

import ast
from pathlib import Path

import nodrix.system.direct_provider_materialization as direct
from nodrix.runtime_components import (
    LoadedApplication,
    LoadedResource,
)
from nodrix.runtime_primitives import (
    RuntimeApplicationBinding,
    RuntimeResourceBinding,
)
from nodrix.system.planning import (
    PlannedApplication,
    PlannedResource,
)


def _resource() -> PlannedResource:
    return PlannedResource(
        ordinal=0,
        name="camera",
        uses="tests.camera",
        target="local",
        backend="local",
        parameters={
            "device": "/dev/video0",
        },
        bindings={
            "session": "ros",
        },
        metadata={
            "label": "front",
        },
        extensions={
            "legacy": {
                "ignored": True,
            },
        },
    )


def _application() -> PlannedApplication:
    return PlannedApplication(
        ordinal=1,
        name="viewer",
        uses="tests.viewer",
        target="local",
        backend="local",
        parameters={
            "mode": "preview",
        },
        resources={
            "camera": "camera",
        },
        metadata={
            "label": "viewer",
        },
        extensions={
            "legacy": {
                "ignored": True,
            },
        },
    )


def test_planned_resource_materializes_runtime_binding():
    planned = _resource()

    binding = (
        direct.runtime_resource_binding_from_planned(
            planned
        )
    )

    assert isinstance(
        binding,
        RuntimeResourceBinding,
    )

    assert binding.uses == planned.uses

    assert dict(
        binding.parameters
    ) == planned.parameters

    assert dict(
        binding.bindings
    ) == planned.bindings


def test_planned_application_materializes_runtime_binding():
    planned = _application()

    binding = (
        direct.runtime_application_binding_from_planned(
            planned
        )
    )

    assert isinstance(
        binding,
        RuntimeApplicationBinding,
    )

    assert binding.uses == planned.uses

    assert dict(
        binding.parameters
    ) == planned.parameters

    assert dict(
        binding.resource_bindings
    ) == planned.resources


def test_direct_resource_uses_shared_materializer(
    monkeypatch,
):
    planned = _resource()
    calls = []

    instance = object()

    expected = LoadedResource(
        name=planned.name,
        uses=planned.uses,
        instance=instance,
        binding=(
            direct.runtime_resource_binding_from_planned(
                planned
            )
        ),
    )

    def materialize(
        name,
        binding,
    ):
        calls.append(
            (
                name,
                binding,
            )
        )

        return expected

    monkeypatch.setattr(
        direct,
        "materialize_runtime_resource",
        materialize,
    )

    loaded = direct.materialize_direct_resource(
        planned
    )

    assert loaded is expected
    assert len(calls) == 1

    name, binding = calls[0]

    assert name == planned.name
    assert binding.uses == planned.uses

    assert dict(
        binding.parameters
    ) == planned.parameters

    assert dict(
        binding.bindings
    ) == planned.bindings


def test_direct_application_uses_shared_materializer(
    monkeypatch,
):
    planned = _application()
    calls = []

    instance = object()

    expected = LoadedApplication(
        name=planned.name,
        uses=planned.uses,
        instance=instance,
        binding=(
            direct.runtime_application_binding_from_planned(
                planned
            )
        ),
    )

    def materialize(
        name,
        binding,
    ):
        calls.append(
            (
                name,
                binding,
            )
        )

        return expected

    monkeypatch.setattr(
        direct,
        "materialize_runtime_application",
        materialize,
    )

    loaded = direct.materialize_direct_application(
        planned
    )

    assert loaded is expected
    assert len(calls) == 1

    name, binding = calls[0]

    assert name == planned.name
    assert binding.uses == planned.uses

    assert dict(
        binding.parameters
    ) == planned.parameters

    assert dict(
        binding.resource_bindings
    ) == planned.resources


def test_direct_provider_materialization_does_not_read_extensions():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_provider_materialization.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        source,
        filename=str(path),
    )

    for node in ast.walk(tree):
        if not isinstance(
            node,
            ast.Attribute,
        ):
            continue

        assert node.attr != "extensions"


def test_direct_provider_materialization_has_no_legacy_model_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_provider_materialization.py"
    )

    tree = ast.parse(
        path.read_text(
            encoding="utf-8",
        ),
        filename=str(path),
    )

    forbidden_names = {
        "PipelineManifest",
        "ProviderResourceConfig",
        "ApplicationConfig",
        "NodeConfig",
        "SystemModel",
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
