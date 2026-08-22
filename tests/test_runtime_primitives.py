from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from nodrix.manifest import EdgeConfig
from nodrix.messages import Message
from nodrix.runtime_components import (
    EdgeQueue,
    Envelope as CompatibilityEnvelope,
    NodeStats as CompatibilityNodeStats,
    Received as CompatibilityReceived,
)
from nodrix.runtime_primitives import (
    Envelope,
    NodeStats,
    Received,
    RuntimeEdgeQueue,
    RuntimeQueueBinding,
)


def test_runtime_primitives_have_no_description_model_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_primitives.py"
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
        "hybrid_runtime",
        "compatibility",
        "system",
    }

    forbidden_names = {
        "PipelineManifest",
        "SystemModel",
        "SystemExecutionPlan",
        "BackendContext",
        "EdgeConfig",
        "NodeConfig",
    }

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            for alias in node.names:
                assert (
                    alias.name.split(".")[-1]
                    not in forbidden_modules
                )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
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


def test_runtime_queue_binding_is_immutable():
    binding = RuntimeQueueBinding(
        source="source.out",
        target="sink.in",
        capacity=2,
        policy="block",
    )

    with pytest.raises(
        FrozenInstanceError,
    ):
        binding.capacity = 4


def test_runtime_edge_queue_preserves_message_reference():
    queue = RuntimeEdgeQueue(
        RuntimeQueueBinding(
            source="source.out",
            target="sink.in",
            capacity=2,
            policy="block",
        )
    )

    message = Message(
        type="test.value/v1",
        payload={
            "value": 42,
        },
    )

    try:
        assert queue.put(
            message
        )

        received = queue.get()

        assert isinstance(
            received,
            Received,
        )

        assert (
            received.message
            is message
        )

        report = queue.report()

        assert report[
            "source"
        ] == "source.out"

        assert report[
            "target"
        ] == "sink.in"

        assert report[
            "capacity"
        ] == 2

        assert report[
            "policy"
        ] == "block"

    finally:
        queue.close()


def test_legacy_edge_queue_is_thin_generic_adapter():
    edge = EdgeConfig.model_validate(
        {
            "from": "source.out",
            "to": "sink.in",
            "queue": {
                "capacity": 3,
                "policy": "latest",
            },
        }
    )

    queue = EdgeQueue(
        edge
    )

    try:
        assert isinstance(
            queue,
            RuntimeEdgeQueue,
        )

        assert (
            queue.edge
            is edge
        )

        assert (
            queue.binding.source
            == edge.source
        )

        assert (
            queue.binding.target
            == edge.target
        )

        assert (
            queue.binding.capacity
            == edge.queue.capacity
        )

        assert (
            queue.binding.policy
            == edge.queue.policy
        )

    finally:
        queue.close()


def test_runtime_components_reexport_existing_primitive_identity():
    assert (
        CompatibilityEnvelope
        is Envelope
    )

    assert (
        CompatibilityReceived
        is Received
    )

    assert (
        CompatibilityNodeStats
        is NodeStats
    )


def test_runtime_primitives_do_not_reference_pipeline_configuration():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_primitives.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    tree = ast.parse(
        source,
        filename=str(path),
    )

    forbidden_names = {
        "PipelineManifest",
        "EdgeConfig",
        "NodeConfig",
        "ProviderResourceConfig",
        "ApplicationConfig",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert (
                node.id
                not in forbidden_names
            )

        elif isinstance(node, ast.Attribute):
            if (
                isinstance(
                    node.value,
                    ast.Name,
                )
                and node.value.id == "self"
            ):
                assert (
                    node.attr
                    != "manifest"
                )
