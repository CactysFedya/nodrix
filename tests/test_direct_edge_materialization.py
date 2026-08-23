from __future__ import annotations

from nodrix.runtime_edge_materialization import (
    RuntimeEdgeBinding,
)
from nodrix.runtime_primitives import (
    RuntimeQueueBinding,
)
from nodrix.system.connection_execution import (
    ResolvedConnectionExecutionPolicy,
    ResolvedConnectionMemoryPolicy,
    ResolvedConnectionQueuePolicy,
)
from nodrix.system.direct_edge_materialization import (
    runtime_edge_binding_from_planned,
)
from nodrix.system.planning import (
    PlannedConnection,
)


def _planned_connection(
    *,
    capacity: int = 5,
    policy: str = "drop_oldest",
    domain: str = "shared",
    allow_copy: bool = False,
) -> PlannedConnection:
    execution = (
        ResolvedConnectionExecutionPolicy(
            queue=(
                ResolvedConnectionQueuePolicy(
                    capacity=capacity,
                    policy=policy,
                )
            ),
            memory=(
                ResolvedConnectionMemoryPolicy(
                    domain=domain,
                    allow_copy=allow_copy,
                )
            ),
        )
    )

    return PlannedConnection.model_validate(
        {
            "ordinal": 3,
            "graph": "main",
            "from": "source.output",
            "to": "sink.input",
            "type_id": "demo.frame",
            "placement_target": "local",
            "backend": "local",
            "execution": execution,
            "metadata": {
                "ignored": True,
            },
            "extensions": {
                "legacy": {
                    "queue": {
                        "capacity": 999,
                    },
                },
            },
        }
    )


def test_planned_connection_becomes_runtime_edge_binding():
    planned = _planned_connection()

    binding = (
        runtime_edge_binding_from_planned(
            planned
        )
    )

    assert isinstance(
        binding,
        RuntimeEdgeBinding,
    )

    assert isinstance(
        binding.queue,
        RuntimeQueueBinding,
    )

    assert (
        binding.queue.source
        == "source.output"
    )

    assert (
        binding.queue.target
        == "sink.input"
    )

    assert (
        binding.queue.capacity
        == 5
    )

    assert (
        binding.queue.policy
        == "drop_oldest"
    )

    assert (
        binding.memory_domain
        == "shared"
    )

    assert (
        binding.allow_copy
        is False
    )


def test_adapter_uses_only_resolved_connection_execution():
    planned = _planned_connection(
        capacity=2,
        policy="latest",
        domain="auto",
        allow_copy=True,
    )

    binding = (
        runtime_edge_binding_from_planned(
            planned
        )
    )

    assert (
        binding.queue.capacity
        == planned.execution.queue.capacity
    )

    assert (
        binding.queue.policy
        == planned.execution.queue.policy
    )

    assert (
        binding.memory_domain
        == planned.execution.memory.domain
    )

    assert (
        binding.allow_copy
        is planned.execution.memory.allow_copy
    )


def test_legacy_extensions_do_not_override_runtime_binding():
    planned = _planned_connection(
        capacity=7,
        policy="block",
        domain="host",
        allow_copy=True,
    )

    binding = (
        runtime_edge_binding_from_planned(
            planned
        )
    )

    assert (
        binding.queue.capacity
        == 7
    )

    assert (
        binding.queue.policy
        == "block"
    )

    assert (
        binding.memory_domain
        == "host"
    )

    assert (
        binding.allow_copy
        is True
    )


def test_adapter_does_not_create_runtime_queue():
    binding = (
        runtime_edge_binding_from_planned(
            _planned_connection()
        )
    )

    assert isinstance(
        binding,
        RuntimeEdgeBinding,
    )

    assert not hasattr(
        binding,
        "put",
    )

    assert not hasattr(
        binding,
        "get",
    )
