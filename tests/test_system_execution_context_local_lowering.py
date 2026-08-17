from __future__ import annotations

from copy import deepcopy

from nodrix.system import (
    Graph,
    LocalBackend,
    NodeInstance,
    SystemModel,
    plan_system,
)
from nodrix.system.execution_context import (
    SystemExecutionContext,
)
from nodrix.system.local_backend import (
    _apply_execution_defaults,
    lower_local_context,
)


def _execution_context() -> SystemExecutionContext:
    return SystemExecutionContext(
        runtime={
            "mode": "realtime",
            "engine": "unified",
            "type_validation": "first",
            "metrics": {
                "enabled": True,
                "interval_ms": 1000,
            },
        },
        node_defaults={
            "demo.worker": {
                "parameters": {
                    "preset_value": "default",
                    "workers": 2,
                },
                "health": {
                    "timeout_ms": 5000,
                    "on_timeout": "report",
                },
            },
        },
        edge_defaults={
            "queue": {
                "capacity": 1,
                "policy": "latest",
            },
        },
        stream_defaults={
            "bind_host": "127.0.0.1",
            "listen_port": 7420,
            "queue": {
                "capacity": 1,
                "policy": "latest",
            },
        },
    )


def test_execution_defaults_merge_under_explicit_values() -> None:
    context = _execution_context()

    document = {
        "runtime": {
            "metrics": {
                "enabled": False,
            },
        },
        "nodes": {
            "worker": {
                "uses": "demo.worker",
                "parameters": {
                    "workers": 8,
                },
                "health": {},
            },
        },
        "edges": [
            {
                "from": "source.output",
                "to": "worker.input",
                "queue": {
                    "capacity": 4,
                },
            },
        ],
        "streams": {
            "exports": [
                {
                    "name": "/demo",
                    "from": "worker.output",
                    "queue": {
                        "capacity": 3,
                    },
                },
            ],
        },
    }

    resolved = _apply_execution_defaults(
        document,
        context,
    )

    assert resolved["runtime"]["mode"] == "realtime"

    assert (
        resolved[
            "runtime"
        ][
            "metrics"
        ][
            "enabled"
        ]
        is False
    )

    assert (
        resolved[
            "runtime"
        ][
            "metrics"
        ][
            "interval_ms"
        ]
        == 1000
    )

    assert (
        resolved[
            "nodes"
        ][
            "worker"
        ][
            "parameters"
        ][
            "preset_value"
        ]
        == "default"
    )

    assert (
        resolved[
            "nodes"
        ][
            "worker"
        ][
            "parameters"
        ][
            "workers"
        ]
        == 8
    )

    assert (
        resolved[
            "nodes"
        ][
            "worker"
        ][
            "health"
        ][
            "timeout_ms"
        ]
        == 5000
    )

    assert (
        resolved[
            "edges"
        ][0][
            "queue"
        ][
            "capacity"
        ]
        == 4
    )

    assert (
        resolved[
            "edges"
        ][0][
            "queue"
        ][
            "policy"
        ]
        == "latest"
    )

    assert (
        resolved[
            "streams"
        ][
            "bind_host"
        ]
        == "127.0.0.1"
    )

    assert (
        resolved[
            "streams"
        ][
            "listen_port"
        ]
        == 7420
    )

    export_queue = (
        resolved[
            "streams"
        ][
            "exports"
        ][0][
            "queue"
        ]
    )

    assert export_queue["capacity"] == 3
    assert export_queue["policy"] == "latest"


def test_execution_default_merge_does_not_mutate_inputs() -> None:
    context = _execution_context()

    document = {
        "runtime": {
            "metrics": {
                "enabled": False,
            },
        },
        "nodes": {},
        "edges": [],
        "streams": {},
    }

    original = deepcopy(
        document
    )

    _apply_execution_defaults(
        document,
        context,
    )

    assert document == original


def test_structural_local_lowering_applies_verified_execution_context() -> None:
    context = _execution_context()

    system = SystemModel(
        name="execution-defaults",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                        parameters={
                            "workers": 8,
                        },
                    ),
                ),
            ),
        ),
    )

    plan = plan_system(
        system,
        execution_context=context,
    )

    backend = LocalBackend()

    backend_context = backend.context(
        plan,
        execution_context=context,
    )

    lowering = lower_local_context(
        backend_context
    )

    manifest = lowering.manifest

    assert manifest.runtime.mode == "realtime"
    assert manifest.runtime.engine == "unified"
    assert manifest.runtime.type_validation == "first"

    assert (
        manifest.runtime.metrics.enabled
        is True
    )

    assert (
        manifest.runtime.metrics.interval_ms
        == 1000
    )

    worker = manifest.nodes[
        "worker"
    ]

    assert worker.parameters[
        "preset_value"
    ] == "default"

    assert worker.parameters[
        "workers"
    ] == 8

    assert (
        worker.health.timeout_ms
        == 5000
    )


def test_local_backend_engine_constraint_wins_over_execution_default() -> None:
    context = SystemExecutionContext(
        runtime={
            "mode": "realtime",
            "engine": "native",
        },
    )

    system = SystemModel(
        name="local-engine",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                    ),
                ),
            ),
        ),
    )

    plan = plan_system(
        system,
        execution_context=context,
    )

    backend = LocalBackend()

    lowering = lower_local_context(
        backend.context(
            plan,
            execution_context=context,
        )
    )

    assert (
        lowering.manifest.runtime.engine
        == "unified"
    )


def test_no_execution_context_keeps_existing_structural_lowering() -> None:
    system = SystemModel(
        name="no-context",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                    ),
                ),
            ),
        ),
    )

    plan = plan_system(
        system
    )

    backend = LocalBackend()

    lowering = lower_local_context(
        backend.context(
            plan
        )
    )

    assert (
        lowering.manifest.runtime.engine
        == "unified"
    )
