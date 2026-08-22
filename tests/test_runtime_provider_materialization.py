from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from nodrix.errors import RuntimeGraphError
import nodrix.runtime_provider_materialization as materialization
from nodrix.runtime_primitives import (
    RuntimeApplicationBinding,
    RuntimeResourceBinding,
)


class _Resource:
    def __init__(
        self,
        parameters,
    ):
        self.parameters = parameters


class _Application:
    def __init__(
        self,
        parameters,
    ):
        self.parameters = parameters

    def configure(self, context):
        return None

    def start(self):
        return None

    def stop(self):
        return None

    def health(self):
        return {
            "status": "ok",
        }


class _BrokenApplication:
    def __init__(
        self,
        parameters,
    ):
        self.parameters = parameters

    def configure(self, context):
        return None

    def start(self):
        return None

    def stop(self):
        return None


def test_materialize_runtime_resource(
    monkeypatch,
):
    descriptor = SimpleNamespace(
        parameters_schema={
            "type": "object",
        }
    )

    candidate = object()
    validation_calls = []

    monkeypatch.setattr(
        materialization,
        "provider_for_resource",
        lambda uses, include_legacy=False: (
            candidate,
            descriptor,
        ),
    )

    monkeypatch.setattr(
        materialization,
        "load_provider_resource",
        lambda uses: _Resource,
    )

    def validate(
        schema,
        parameters,
        *,
        location,
    ):
        validation_calls.append(
            (
                schema,
                parameters,
                location,
            )
        )

    monkeypatch.setattr(
        materialization,
        "validate_provider_parameters",
        validate,
    )

    binding = RuntimeResourceBinding(
        uses="tests.resource",
        parameters={
            "device": "/dev/test",
        },
        bindings={
            "session": "ros",
        },
    )

    loaded = (
        materialization.materialize_runtime_resource(
            "camera",
            binding,
        )
    )

    assert loaded.name == "camera"
    assert loaded.uses == "tests.resource"
    assert loaded.binding is binding

    assert isinstance(
        loaded.instance,
        _Resource,
    )

    assert loaded.instance.parameters == {
        "device": "/dev/test",
    }

    assert isinstance(
        loaded.instance.parameters,
        dict,
    )

    assert validation_calls == [
        (
            descriptor.parameters_schema,
            {
                "device": "/dev/test",
            },
            "resources.camera.parameters",
        )
    ]


def test_materialize_runtime_application(
    monkeypatch,
):
    descriptor = SimpleNamespace(
        parameters_schema={}
    )

    monkeypatch.setattr(
        materialization,
        "provider_for_application",
        lambda uses, include_legacy=False: (
            object(),
            descriptor,
        ),
    )

    monkeypatch.setattr(
        materialization,
        "load_provider_application",
        lambda uses: _Application,
    )

    calls = []

    monkeypatch.setattr(
        materialization,
        "validate_provider_parameters",
        lambda schema, parameters, *, location: (
            calls.append(
                (
                    schema,
                    parameters,
                    location,
                )
            )
        ),
    )

    binding = RuntimeApplicationBinding(
        uses="tests.application",
        parameters={
            "mode": "test",
        },
        resource_bindings={
            "camera": "front",
        },
    )

    loaded = (
        materialization.materialize_runtime_application(
            "viewer",
            binding,
        )
    )

    assert loaded.name == "viewer"
    assert loaded.binding is binding

    assert isinstance(
        loaded.instance,
        _Application,
    )

    assert loaded.instance.parameters == {
        "mode": "test",
    }

    assert calls == [
        (
            descriptor.parameters_schema,
            {
                "mode": "test",
            },
            "applications.viewer.parameters",
        )
    ]


def test_application_materializer_rejects_incomplete_lifecycle(
    monkeypatch,
):
    descriptor = SimpleNamespace(
        parameters_schema={}
    )

    monkeypatch.setattr(
        materialization,
        "provider_for_application",
        lambda uses, include_legacy=False: (
            object(),
            descriptor,
        ),
    )

    monkeypatch.setattr(
        materialization,
        "load_provider_application",
        lambda uses: _BrokenApplication,
    )

    monkeypatch.setattr(
        materialization,
        "validate_provider_parameters",
        lambda *args, **kwargs: None,
    )

    binding = RuntimeApplicationBinding(
        uses="tests.application",
        parameters={},
        resource_bindings={},
    )

    with pytest.raises(
        RuntimeGraphError,
        match=r"health\(\)",
    ):
        materialization.materialize_runtime_application(
            "viewer",
            binding,
        )


def test_resource_materializer_rejects_unknown_provider(
    monkeypatch,
):
    monkeypatch.setattr(
        materialization,
        "provider_for_resource",
        lambda uses, include_legacy=False: None,
    )

    binding = RuntimeResourceBinding(
        uses="missing.resource",
        parameters={},
        bindings={},
    )

    with pytest.raises(
        RuntimeGraphError,
        match="Unknown provider resource",
    ):
        materialization.materialize_runtime_resource(
            "missing",
            binding,
        )


def test_application_materializer_rejects_unknown_provider(
    monkeypatch,
):
    monkeypatch.setattr(
        materialization,
        "provider_for_application",
        lambda uses, include_legacy=False: None,
    )

    binding = RuntimeApplicationBinding(
        uses="missing.application",
        parameters={},
        resource_bindings={},
    )

    with pytest.raises(
        RuntimeGraphError,
        match="Unknown provider application",
    ):
        materialization.materialize_runtime_application(
            "missing",
            binding,
        )


def test_provider_materializer_has_no_description_model_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_provider_materialization.py"
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
        "SystemModel",
        "SystemExecutionPlan",
        "PlannedResource",
        "PlannedApplication",
    }

    for node in ast.walk(tree):
        if not isinstance(
            node,
            ast.ImportFrom,
        ):
            continue

        for alias in node.names:
            assert (
                alias.name
                not in forbidden_names
            )


def test_pipeline_builder_delegates_provider_materialization():
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
        "materialize_runtime_resource"
        in source
    )

    assert (
        "materialize_runtime_application"
        in source
    )

    assert (
        "provider_for_resource"
        not in source
    )

    assert (
        "load_provider_resource"
        not in source
    )

    assert (
        "provider_for_application"
        not in source
    )

    assert (
        "load_provider_application"
        not in source
    )
