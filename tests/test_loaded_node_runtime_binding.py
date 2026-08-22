from __future__ import annotations

from pathlib import Path

from nodrix.runtime_components import (
    LoadedNode,
)
from nodrix.runtime_primitives import (
    RuntimeNodeBinding,
)


def test_loaded_node_owns_runtime_binding_not_node_config():
    annotations = LoadedNode.__annotations__

    assert "binding" in annotations
    assert "config" not in annotations

    assert (
        annotations["binding"]
        == "RuntimeNodeBinding"
        or annotations["binding"]
        is RuntimeNodeBinding
    )


def test_runtime_consumers_do_not_read_loaded_config():
    root = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
    )

    for filename in (
        "runtime_builder.py",
        "runtime_workers.py",
        "runtime_execution.py",
        "hybrid_runtime.py",
    ):
        source = (
            root
            / filename
        ).read_text(
            encoding="utf-8",
        )

        assert "loaded.config" not in source


def test_pipeline_builder_materializes_loaded_node_binding():
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
        "runtime_node_binding_from_config"
        in source
    )

    assert (
        "binding=runtime_node_binding_from_config("
        in source
    )


def test_worker_uses_runtime_binding_mechanics():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_workers.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    required = {
        "loaded.binding.failure_policy",
        "loaded.binding.fallback_uses",
        "loaded.binding.synchronization_policy",
        "loaded.binding.synchronization_tolerance_ns",
        "loaded.binding.max_message_bytes",
        "binding.health_timeout_ns",
        "binding.health_on_timeout",
    }

    for token in required:
        assert token in source

    assert "binding = loaded.binding" in source
