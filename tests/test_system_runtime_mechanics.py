from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nodrix.system.execution_context import (
    SystemExecutionContext,
)
from nodrix.system.runtime_mechanics import (
    RuntimeMechanicsResolutionError,
    resolve_runtime_mechanics,
)


def test_missing_execution_context_has_no_runtime_mechanics():
    resolved = (
        resolve_runtime_mechanics(
            None
        )
    )

    assert (
        resolved.telemetry_sample_capacity
        is None
    )

    assert resolved.process is None


def test_missing_mechanics_does_not_invent_defaults():
    context = SystemExecutionContext(
        runtime={
            "mode": "realtime",
            "engine": "unified",
        },
    )

    resolved = (
        resolve_runtime_mechanics(
            context
        )
    )

    assert (
        resolved.telemetry_sample_capacity
        is None
    )

    assert resolved.process is None


def test_legacy_runtime_memory_is_not_canonical_process_mechanics():
    context = SystemExecutionContext(
        runtime={
            "memory": {
                "shared_pool": {
                    "block_size": 8 * 1024 * 1024,
                    "capacity": 8,
                    "threshold": 64 * 1024,
                },
                "process_output_pool": {
                    "block_size": 8 * 1024 * 1024,
                    "capacity": 8,
                    "threshold": 64 * 1024,
                },
            },
            "telemetry_samples": 4096,
        },
    )

    resolved = (
        resolve_runtime_mechanics(
            context
        )
    )

    assert (
        resolved.telemetry_sample_capacity
        is None
    )

    assert resolved.process is None


def test_explicit_runtime_mechanics_are_resolved():
    context = SystemExecutionContext(
        runtime={
            "mechanics": {
                "telemetry": {
                    "sample_capacity": 8192,
                },
                "process": {
                    "input_pool": {
                        "block_size": 4 * 1024 * 1024,
                        "capacity": 16,
                        "threshold": 32 * 1024,
                    },
                    "output_pool": {
                        "block_size": 2 * 1024 * 1024,
                        "capacity": 32,
                        "threshold": 16 * 1024,
                    },
                },
            },
        },
    )

    resolved = (
        resolve_runtime_mechanics(
            context
        )
    )

    assert (
        resolved.telemetry_sample_capacity
        == 8192
    )

    assert resolved.process is not None

    assert (
        resolved.process.input_pool.block_size
        == 4 * 1024 * 1024
    )

    assert (
        resolved.process.input_pool.capacity
        == 16
    )

    assert (
        resolved.process.input_pool.threshold
        == 32 * 1024
    )

    assert (
        resolved.process.output_pool.block_size
        == 2 * 1024 * 1024
    )

    assert (
        resolved.process.output_pool.capacity
        == 32
    )

    assert (
        resolved.process.output_pool.threshold
        == 16 * 1024
    )


def test_process_mechanics_require_both_pools():
    context = SystemExecutionContext(
        runtime={
            "mechanics": {
                "process": {
                    "input_pool": {
                        "block_size": 4096,
                        "capacity": 1,
                        "threshold": 0,
                    },
                },
            },
        },
    )

    with pytest.raises(
        RuntimeMechanicsResolutionError,
        match="output_pool",
    ):
        resolve_runtime_mechanics(
            context
        )


@pytest.mark.parametrize(
    (
        "field",
        "value",
    ),
    [
        (
            "block_size",
            1024,
        ),
        (
            "capacity",
            0,
        ),
        (
            "threshold",
            -1,
        ),
    ],
)
def test_process_pool_values_are_bounded(
    field,
    value,
):
    pool = {
        "block_size": 4096,
        "capacity": 1,
        "threshold": 0,
    }

    pool[field] = value

    context = SystemExecutionContext(
        runtime={
            "mechanics": {
                "process": {
                    "input_pool": pool,
                    "output_pool": {
                        "block_size": 4096,
                        "capacity": 1,
                        "threshold": 0,
                    },
                },
            },
        },
    )

    with pytest.raises(
        RuntimeMechanicsResolutionError,
    ):
        resolve_runtime_mechanics(
            context
        )


def test_runtime_mechanics_reject_unknown_canonical_fields():
    context = SystemExecutionContext(
        runtime={
            "mechanics": {
                "mystery": {
                    "enabled": True,
                },
            },
        },
    )

    with pytest.raises(
        RuntimeMechanicsResolutionError,
        match="mystery",
    ):
        resolve_runtime_mechanics(
            context
        )


def test_runtime_mechanics_has_no_legacy_or_backend_dependency():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "runtime_mechanics.py"
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
        "compatibility",
        "local_backend",
        "hybrid_runtime",
        "direct_preparation",
        "runtime_builder",
    }

    forbidden_names = {
        "PipelineManifest",
        "RuntimeConfig",
        "LocalBackend",
        "HybridPipelineRuntime",
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


def test_runtime_mechanics_does_not_define_legacy_defaults():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "nodrix"
        / "system"
        / "runtime_mechanics.py"
    )

    source = path.read_text(
        encoding="utf-8",
    )

    forbidden = {
        "telemetry_samples",
        "shared_pool",
        "process_output_pool",
        "8 * 1024 * 1024",
        "64 * 1024",
        "= 4096",
    }

    for token in forbidden:
        assert token not in source


def test_direct_preparation_preserves_resolved_runtime_mechanics(
    monkeypatch,
    tmp_path,
):
    from types import SimpleNamespace

    from nodrix.system import (
        direct_preparation,
    )
    from nodrix.system.direct_environment import (
        DirectExecutionEnvironment,
    )

    execution_context = (
        SystemExecutionContext(
            runtime={
                "mechanics": {
                    "telemetry": {
                        "sample_capacity": 1234,
                    },
                },
            },
        )
    )

    context = SimpleNamespace(
        backend="local",
        resources=(),
        applications=(),
        nodes=(),
        execution_context=execution_context,
    )

    monkeypatch.setattr(
        direct_preparation,
        "materialize_direct_context",
        lambda value: (
            SimpleNamespace(
                context=value,
            )
        ),
    )

    prepared = (
        direct_preparation
        .prepare_direct_execution(
            context,
            environment=(
                DirectExecutionEnvironment(
                    base_dir=tmp_path,
                )
            ),
        )
    )

    assert (
        prepared.payload
        .mechanics
        .telemetry_sample_capacity
        == 1234
    )

    assert (
        prepared.payload
        .mechanics
        .process
        is None
    )


def test_runtime_mechanics_has_canonical_graph_memory_policy():
    resolved = (
        resolve_runtime_mechanics(
            None
        )
    )

    assert (
        resolved.graph_memory
        .default_domain
        == "auto"
    )

    assert (
        resolved.graph_memory
        .forbid_implicit_copies
        is False
    )


def test_explicit_graph_memory_mechanics_are_resolved():
    context = SystemExecutionContext(
        runtime={
            "mechanics": {
                "graph_memory": {
                    "default_domain": "shared",
                    "forbid_implicit_copies": True,
                },
            },
        },
    )

    resolved = (
        resolve_runtime_mechanics(
            context
        )
    )

    assert (
        resolved.graph_memory
        .default_domain
        == "shared"
    )

    assert (
        resolved.graph_memory
        .forbid_implicit_copies
        is True
    )


def test_partial_graph_memory_mechanics_keep_canonical_base_policy():
    context = SystemExecutionContext(
        runtime={
            "mechanics": {
                "graph_memory": {
                    "forbid_implicit_copies": True,
                },
            },
        },
    )

    resolved = (
        resolve_runtime_mechanics(
            context
        )
    )

    assert (
        resolved.graph_memory
        .default_domain
        == "auto"
    )

    assert (
        resolved.graph_memory
        .forbid_implicit_copies
        is True
    )


def test_legacy_runtime_memory_does_not_drive_graph_memory_mechanics():
    context = SystemExecutionContext(
        runtime={
            "memory": {
                "default_domain": "shared",
                "forbid_implicit_copies": True,
            },
        },
    )

    resolved = (
        resolve_runtime_mechanics(
            context
        )
    )

    assert (
        resolved.graph_memory
        .default_domain
        == "auto"
    )

    assert (
        resolved.graph_memory
        .forbid_implicit_copies
        is False
    )


def test_graph_memory_rejects_empty_default_domain():
    context = SystemExecutionContext(
        runtime={
            "mechanics": {
                "graph_memory": {
                    "default_domain": "",
                },
            },
        },
    )

    with pytest.raises(
        RuntimeMechanicsResolutionError,
        match="default_domain",
    ):
        resolve_runtime_mechanics(
            context
        )


def test_graph_memory_rejects_non_boolean_copy_policy():
    context = SystemExecutionContext(
        runtime={
            "mechanics": {
                "graph_memory": {
                    "forbid_implicit_copies": 1,
                },
            },
        },
    )

    with pytest.raises(
        RuntimeMechanicsResolutionError,
        match="forbid_implicit_copies",
    ):
        resolve_runtime_mechanics(
            context
        )


def test_graph_memory_rejects_unknown_fields():
    context = SystemExecutionContext(
        runtime={
            "mechanics": {
                "graph_memory": {
                    "mystery": True,
                },
            },
        },
    )

    with pytest.raises(
        RuntimeMechanicsResolutionError,
        match="mystery",
    ):
        resolve_runtime_mechanics(
            context
        )
