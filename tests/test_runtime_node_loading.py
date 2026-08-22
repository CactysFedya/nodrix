from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nodrix.errors import RuntimeGraphError
from nodrix.node import Node
from nodrix import runtime_node_loading


class _DemoNode(Node):
    pass


class _NativeProbeNode(Node):
    def __init__(
        self,
        library,
        node_type,
        parameters,
    ):
        super().__init__(
            parameters
        )
        self.library = library
        self.node_type = node_type


def test_python_node_reference_is_resolved_and_loaded(
    monkeypatch,
    tmp_path,
):
    calls = {}

    def resolve(reference):
        calls[
            "resolve"
        ] = reference
        return "resolved.module:DemoNode"

    def load(reference, base_dir=None):
        calls[
            "load_reference"
        ] = reference
        calls[
            "base_dir"
        ] = base_dir
        return _DemoNode

    monkeypatch.setattr(
        runtime_node_loading,
        "resolve_package_node",
        resolve,
    )

    monkeypatch.setattr(
        runtime_node_loading,
        "load_node_class",
        load,
    )

    parameters = {
        "workers": 4,
    }

    node = (
        runtime_node_loading
        .load_runtime_node(
            "demo/package",
            parameters,
            base_dir=tmp_path,
        )
    )

    assert isinstance(
        node,
        _DemoNode,
    )

    assert calls == {
        "resolve": "demo/package",
        "load_reference": (
            "resolved.module:DemoNode"
        ),
        "base_dir": tmp_path,
    }

    assert (
        node.parameters
        is parameters
    )


def test_package_resolution_can_produce_native_reference(
    monkeypatch,
    tmp_path,
):
    library = (
        tmp_path
        / "libdemo.so"
    )

    library.write_bytes(
        b"probe"
    )

    monkeypatch.setattr(
        runtime_node_loading,
        "resolve_package_node",
        lambda reference: (
            f"native:{library}#worker"
        ),
    )

    monkeypatch.setattr(
        runtime_node_loading,
        "NativePluginNode",
        _NativeProbeNode,
    )

    parameters = {
        "mode": "fast",
    }

    node = (
        runtime_node_loading
        .load_runtime_node(
            "demo/worker",
            parameters,
            base_dir=tmp_path,
        )
    )

    assert isinstance(
        node,
        _NativeProbeNode,
    )

    assert (
        node.library
        == library
    )

    assert (
        node.node_type
        == "worker"
    )

    assert (
        node.parameters
        is parameters
    )


def test_relative_native_library_is_resolved_from_base_dir(
    monkeypatch,
    tmp_path,
):
    plugin_dir = (
        tmp_path
        / "plugins"
    )

    plugin_dir.mkdir()

    library = (
        plugin_dir
        / "libdemo.so"
    )

    library.write_bytes(
        b"probe"
    )

    monkeypatch.setattr(
        runtime_node_loading,
        "NativePluginNode",
        _NativeProbeNode,
    )

    node = (
        runtime_node_loading
        .load_runtime_node(
            (
                "native:"
                "plugins/libdemo.so"
                "#worker"
            ),
            {},
            base_dir=tmp_path,
        )
    )

    assert (
        node.library
        == library.resolve()
    )

    assert (
        node.node_type
        == "worker"
    )


def test_native_reference_requires_node_type(
    tmp_path,
):
    library = (
        tmp_path
        / "libdemo.so"
    )

    library.write_bytes(
        b"probe"
    )

    with pytest.raises(
        RuntimeGraphError,
        match="must use",
    ):
        runtime_node_loading.load_runtime_node(
            f"native:{library}",
            {},
            base_dir=tmp_path,
        )


def test_native_library_must_exist(
    tmp_path,
):
    missing = (
        tmp_path
        / "missing.so"
    )

    with pytest.raises(
        RuntimeGraphError,
        match="does not exist",
    ):
        runtime_node_loading.load_runtime_node(
            f"native:{missing}#worker",
            {},
            base_dir=tmp_path,
        )


def test_builtin_native_namespace_is_rejected_by_unified_loader(
    tmp_path,
):
    with pytest.raises(
        RuntimeGraphError,
        match="engine: native",
    ):
        runtime_node_loading.load_runtime_node(
            "native.identity",
            {},
            base_dir=tmp_path,
        )


def test_loader_does_not_validate_or_resolve_runtime_policy():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_node_loading.py"
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
        "runtime_components",
        "runtime_primitives",
        "runtime_workers",
        "hybrid_runtime",
        "local_backend",
        "planning",
        "execution_context",
        "node_execution",
        "process_host",
        "memory",
    }

    forbidden_names = {
        "PipelineManifest",
        "NodeConfig",
        "RuntimeNodeBinding",
        "PlannedNode",
        "SystemExecutionContext",
        "ProcessNodeProxy",
        "ProcessSourceProxy",
        "NodeStats",
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


def test_loader_has_no_hidden_parameter_validation():
    source = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "runtime_node_loading.py"
    ).read_text(
        encoding="utf-8",
    )

    assert (
        "validate_parameters"
        not in source
    )

    assert (
        "failure_policy"
        not in source
    )

    assert (
        "telemetry_samples"
        not in source
    )

    assert (
        "shared_pool"
        not in source
    )


def test_runtime_builder_wrapper_uses_shared_loader(
    monkeypatch,
    tmp_path,
):
    from nodrix import runtime_builder

    expected = _DemoNode(
        {
            "expected": True,
        }
    )

    calls = {}

    def load(
        uses,
        parameters,
        *,
        base_dir,
    ):
        calls["uses"] = uses
        calls["parameters"] = parameters
        calls["base_dir"] = base_dir
        return expected

    monkeypatch.setattr(
        runtime_builder,
        "load_runtime_node",
        load,
    )

    runtime = (
        runtime_builder
        .RuntimeBuildMixin()
    )

    runtime.base_dir = tmp_path

    parameters = {
        "workers": 8,
    }

    actual = runtime._load_node(
        "demo.worker",
        parameters,
    )

    assert actual is expected

    assert calls == {
        "uses": "demo.worker",
        "parameters": parameters,
        "base_dir": tmp_path,
    }
