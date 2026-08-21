from __future__ import annotations

import ast
from pathlib import Path

from nodrix.system.backend import (
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionStatus,
    PreparedExecution,
)
from nodrix.system.direct_executor import DirectSystemExecutor


class _ContractProbe:
    def prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        raise NotImplementedError

    def start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        raise NotImplementedError

    def inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        raise NotImplementedError

    def stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None = None,
    ) -> BackendExecutionStatus:
        raise NotImplementedError


def test_direct_system_executor_is_structural_internal_contract():
    assert isinstance(
        _ContractProbe(),
        DirectSystemExecutor,
    )


def test_direct_executor_reuses_canonical_backend_lifecycle_types():
    annotations = DirectSystemExecutor.prepare.__annotations__
    assert annotations["context"] == "BackendContext"
    assert annotations["return"] == "PreparedExecution"

    annotations = DirectSystemExecutor.start.__annotations__
    assert annotations["prepared"] == "PreparedExecution"
    assert annotations["return"] == "BackendExecutionHandle"

    annotations = DirectSystemExecutor.inspect.__annotations__
    assert annotations["handle"] == "BackendExecutionHandle"
    assert annotations["return"] == "BackendExecutionStatus"

    annotations = DirectSystemExecutor.stop.__annotations__
    assert annotations["handle"] == "BackendExecutionHandle"
    assert annotations["timeout_seconds"] == "float | None"
    assert annotations["return"] == "BackendExecutionStatus"


def test_direct_executor_has_no_legacy_runtime_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_executor.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )
    tree = ast.parse(
        source,
        filename=str(path),
    )

    forbidden_modules = {
        "nodrix.manifest",
        "nodrix.hybrid_runtime",
        "manifest",
        "hybrid_runtime",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_modules

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module not in forbidden_modules
            assert not module.endswith(".manifest")
            assert not module.endswith(".hybrid_runtime")


def test_direct_executor_does_not_create_parallel_semantic_inputs():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "direct_executor.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )
    tree = ast.parse(
        source,
        filename=str(path),
    )

    imported_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(
                alias.name
                for alias in node.names
            )

    assert "SystemModel" not in imported_names
    assert "SystemExecutionPlan" not in imported_names
    assert "PipelineManifest" not in imported_names


def test_direct_executor_contract_is_minimal():
    public_methods = {
        name
        for name, value in DirectSystemExecutor.__dict__.items()
        if callable(value)
        and not name.startswith("_")
    }

    assert public_methods == {
        "prepare",
        "start",
        "inspect",
        "stop",
    }
