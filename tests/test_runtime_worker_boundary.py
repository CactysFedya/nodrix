from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from nodrix.messages import Message
from nodrix.runtime_workers import RuntimeWorkerMixin


class _WorkerProbe(RuntimeWorkerMixin):
    def __init__(self) -> None:
        self._runtime_type_validation = "off"
        self._message_scope_id = "system-under-test"
        self._validated_ports = set()


def _runtime_workers_tree() -> ast.Module:
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_workers.py"
    )

    return ast.parse(
        path.read_text(
            encoding="utf-8",
        ),
        filename=str(path),
    )


def test_worker_hot_path_has_no_manifest_access():
    tree = _runtime_workers_tree()

    for node in ast.walk(tree):
        if not isinstance(
            node,
            ast.Attribute,
        ):
            continue

        if (
            isinstance(
                node.value,
                ast.Name,
            )
            and node.value.id == "self"
        ):
            assert node.attr != "manifest"


def test_worker_uses_generic_runtime_queue_primitives():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_workers.py"
    )

    tree = _runtime_workers_tree()

    primitive_imports: set[str] = set()
    component_imports: set[str] = set()

    for node in tree.body:
        if not isinstance(
            node,
            ast.ImportFrom,
        ):
            continue

        names = {
            alias.name
            for alias in node.names
        }

        if node.module == "runtime_primitives":
            primitive_imports |= names

        if node.module == "runtime_components":
            component_imports |= names

    assert {
        "Received",
        "RuntimeAsyncBridge",
        "RuntimeEdgeQueue",
        "_EOS",
        "_estimate_message_bytes",
    } <= primitive_imports

    assert component_imports == {
        "LoadedNode",
    }


def test_worker_does_not_reach_through_legacy_edge_config():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_workers.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    assert "edge.edge" not in source
    assert "edge.binding.target" in source


def test_type_validation_mode_is_runtime_host_state():
    worker = _WorkerProbe()

    loaded = SimpleNamespace(
        name="node",
        stats=SimpleNamespace(
            type_validations=0,
        ),
    )

    message = Message(
        type="does.not.need.validation",
        payload=object(),
    )

    worker._validate_payload(
        loaded,
        "output",
        message,
    )

    assert (
        loaded.stats.type_validations
        == 0
    )


def test_hybrid_runtime_materializes_worker_mechanics_once():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "hybrid_runtime.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    assert (
        "self._runtime_type_validation"
        in source
    )

    assert (
        "self._message_scope_id"
        in source
    )

    assert (
        "self.manifest.runtime.type_validation"
        in source
    )

    assert (
        "self.manifest.metadata.name"
        in source
    )
