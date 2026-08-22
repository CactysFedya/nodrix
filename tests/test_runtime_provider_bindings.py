from __future__ import annotations

from dataclasses import (
    FrozenInstanceError,
    MISSING,
    fields,
)

import pytest

from nodrix.manifest import (
    ApplicationConfig,
    ProviderResourceConfig,
)
from nodrix.runtime_components import (
    LoadedApplication,
    LoadedResource,
    runtime_application_binding_from_config,
    runtime_resource_binding_from_config,
)
from nodrix.runtime_primitives import (
    RuntimeApplicationBinding,
    RuntimeResourceBinding,
)


def test_runtime_provider_bindings_have_no_hidden_defaults():
    for binding_type in (
        RuntimeResourceBinding,
        RuntimeApplicationBinding,
    ):
        for definition in fields(
            binding_type
        ):
            assert (
                definition.default
                is MISSING
            )
            assert (
                definition.default_factory
                is MISSING
            )


def test_resource_config_materializes_runtime_binding():
    config = ProviderResourceConfig.model_validate(
        {
            "uses": "tests.resource",
            "parameters": {
                "device": "/dev/test",
            },
            "bindings": {
                "session": "ros",
            },
        }
    )

    binding = runtime_resource_binding_from_config(
        config
    )

    assert isinstance(
        binding,
        RuntimeResourceBinding,
    )

    assert binding.uses == config.uses

    assert dict(
        binding.parameters
    ) == config.parameters

    assert dict(
        binding.bindings
    ) == config.bindings


def test_application_config_materializes_runtime_binding():
    config = ApplicationConfig.model_validate(
        {
            "uses": "tests.application",
            "parameters": {
                "mode": "test",
            },
            "bindings": {
                "camera": "front_camera",
            },
        }
    )

    binding = runtime_application_binding_from_config(
        config
    )

    assert isinstance(
        binding,
        RuntimeApplicationBinding,
    )

    assert binding.uses == config.uses

    assert dict(
        binding.parameters
    ) == config.parameters

    assert dict(
        binding.resource_bindings
    ) == config.bindings


def test_runtime_provider_bindings_are_immutable():
    resource = RuntimeResourceBinding(
        uses="tests.resource",
        parameters={
            "value": 1,
        },
        bindings={
            "session": "ros",
        },
    )

    application = RuntimeApplicationBinding(
        uses="tests.application",
        parameters={
            "value": 2,
        },
        resource_bindings={
            "camera": "front",
        },
    )

    with pytest.raises(
        FrozenInstanceError,
    ):
        resource.uses = "other"

    with pytest.raises(
        TypeError,
    ):
        resource.bindings[
            "other"
        ] = "x"

    with pytest.raises(
        TypeError,
    ):
        application.resource_bindings[
            "other"
        ] = "x"


def test_loaded_provider_components_use_runtime_bindings():
    resource_annotations = (
        LoadedResource.__annotations__
    )

    application_annotations = (
        LoadedApplication.__annotations__
    )

    assert "binding" in resource_annotations
    assert "config" not in resource_annotations

    assert "binding" in application_annotations
    assert "config" not in application_annotations


def test_provider_adapters_snapshot_top_level_mappings():
    resource_config = ProviderResourceConfig.model_validate(
        {
            "uses": "tests.resource",
            "parameters": {
                "value": 1,
            },
            "bindings": {
                "session": "ros",
            },
        }
    )

    application_config = ApplicationConfig.model_validate(
        {
            "uses": "tests.application",
            "parameters": {
                "value": 2,
            },
            "bindings": {
                "camera": "front",
            },
        }
    )

    resource = runtime_resource_binding_from_config(
        resource_config
    )

    application = runtime_application_binding_from_config(
        application_config
    )

    resource_config.parameters[
        "later"
    ] = True

    resource_config.bindings[
        "later"
    ] = "x"

    application_config.parameters[
        "later"
    ] = True

    application_config.bindings[
        "later"
    ] = "x"

    assert "later" not in resource.parameters
    assert "later" not in resource.bindings
    assert "later" not in application.parameters

    assert (
        "later"
        not in application.resource_bindings
    )


def test_integration_runtime_uses_provider_bindings_not_configs():
    path = (
        __import__("pathlib").Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "integration_runtime.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    assert (
        "loaded.binding.bindings.items()"
        in source
    )

    assert (
        "loaded.binding.resource_bindings.items()"
        in source
    )

    assert (
        "loaded.config.bindings"
        not in source
    )

    assert (
        "loaded.configured"
        in source
    )
