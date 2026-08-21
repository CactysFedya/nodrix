from __future__ import annotations

from types import (
    ModuleType,
    SimpleNamespace,
)
import sys

import pytest

import nodrix.local_project_catalog as module
from nodrix.local_project_catalog import (
    local_project_definition_catalog,
)
from nodrix.sdk.definitions import (
    MessageDefinition,
    NodeDefinition,
    ResourceDefinition,
)


def _node_definition() -> NodeDefinition:
    return NodeDefinition(
        name="demo.worker",
        inputs=(),
        outputs=(),
        parameters=(),
        dependencies=(),
        implementation=object(),
    )


def _resource_definition() -> ResourceDefinition:
    return ResourceDefinition(
        name="demo.resource",
        parameters=(),
        implementation=object(),
    )


def _message_definition() -> MessageDefinition:
    return MessageDefinition(
        type_id="demo.message",
        version=1,
        python_type=dict,
    )


def test_local_project_catalog_collects_neutral_sdk_definitions(
    tmp_path,
    monkeypatch,
) -> None:
    node_definition = (
        _node_definition()
    )

    resource_definition = (
        _resource_definition()
    )

    message_definition = (
        _message_definition()
    )

    class Node:
        __plyctl_definition__ = (
            node_definition
        )

    class Resource:
        __plyctl_definition__ = (
            resource_definition
        )

    class Message:
        __plyctl_definition__ = (
            message_definition
        )

    module_name = (
        "components.catalog_test"
    )

    local_module = ModuleType(
        module_name
    )

    local_module.Message = (
        Message
    )

    monkeypatch.setitem(
        sys.modules,
        module_name,
        local_module,
    )

    project = SimpleNamespace(
        compiled=SimpleNamespace(
            provider_runtime=SimpleNamespace(
                nodes={
                    "worker": Node,
                },
                resources={
                    "resource": Resource,
                },
            )
        ),
        module_names=(
            module_name,
        ),
    )

    reset_calls: list[
        str
    ] = []

    monkeypatch.setattr(
        module,
        "reset_local_development_modules",
        lambda: reset_calls.append(
            "reset"
        ),
    )

    monkeypatch.setattr(
        module,
        "compile_local_project",
        lambda path: project,
    )

    catalog = (
        local_project_definition_catalog(
            tmp_path
        )
    )

    assert dict(
        catalog.nodes
    ) == {
        "demo.worker": (
            node_definition
        ),
    }

    assert dict(
        catalog.resources
    ) == {
        "demo.resource": (
            resource_definition
        ),
    }

    assert dict(
        catalog.messages
    ) == {
        "demo.message": (
            message_definition
        ),
    }

    assert reset_calls == [
        "reset",
        "reset",
    ]


def test_local_project_catalog_cleans_modules_when_compilation_fails(
    tmp_path,
    monkeypatch,
) -> None:
    reset_calls: list[
        str
    ] = []

    monkeypatch.setattr(
        module,
        "reset_local_development_modules",
        lambda: reset_calls.append(
            "reset"
        ),
    )

    def fail(
        path,
    ):
        del path

        raise RuntimeError(
            "synthetic compile failure"
        )

    monkeypatch.setattr(
        module,
        "compile_local_project",
        fail,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "synthetic compile failure"
        ),
    ):
        local_project_definition_catalog(
            tmp_path
        )

    # Cleanup is mandatory even after failed compilation.
    assert reset_calls == [
        "reset",
        "reset",
    ]
