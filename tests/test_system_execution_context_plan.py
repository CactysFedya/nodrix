from __future__ import annotations

import hashlib
import json

from nodrix.system import (
    Graph,
    NodeInstance,
    SystemModel,
    plan_system,
)
from nodrix.system.canonical import (
    system_plan_digest,
    system_plan_record,
)
from nodrix.system.execution_context import (
    SystemExecutionContext,
    system_execution_context_digest,
)


def _system() -> SystemModel:
    return SystemModel(
        name="context-plan-test",
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


def _context(
    *,
    config_file: str,
    mode: str = "realtime",
) -> SystemExecutionContext:
    return SystemExecutionContext(
        variables={
            "FASTLIO_CONFIG_FILE": config_file,
        },
        runtime={
            "mode": mode,
            "engine": "unified",
        },
        edge_defaults={
            "queue": {
                "capacity": 1,
                "policy": "latest",
            },
        },
    )


def test_execution_context_changes_plan_not_system_revision() -> None:
    system = _system()

    first = plan_system(
        system,
        execution_context=_context(
            config_file="field.yaml",
        ),
    )

    second = plan_system(
        system,
        execution_context=_context(
            config_file="lab.yaml",
        ),
    )

    assert (
        first.system_sha256
        == second.system_sha256
    )

    assert (
        first.execution_context_sha256
        != second.execution_context_sha256
    )

    assert (
        system_plan_digest(first)
        != system_plan_digest(second)
    )

    assert (
        system_plan_record(first).plan_id
        != system_plan_record(second).plan_id
    )


def test_plan_context_binding_matches_effective_context_digest() -> None:
    context = _context(
        config_file="mid360s.yaml",
    )

    plan = plan_system(
        _system(),
        execution_context=context,
    )

    assert (
        plan.execution_context_sha256
        == system_execution_context_digest(
            context
        )
    )


def test_identical_effective_context_has_identical_plan_identity() -> None:
    first_context = _context(
        config_file="mid360s.yaml",
    )

    second_context = _context(
        config_file="mid360s.yaml",
    )

    first = plan_system(
        _system(),
        execution_context=first_context,
    )

    second = plan_system(
        _system(),
        execution_context=second_context,
    )

    assert (
        first.execution_context_sha256
        == second.execution_context_sha256
    )

    assert (
        system_plan_digest(first)
        == system_plan_digest(second)
    )

    assert (
        system_plan_record(first).plan_id
        == system_plan_record(second).plan_id
    )


def test_plan_does_not_materialize_execution_variables() -> None:
    secret = "do-not-store-this-value"

    context = SystemExecutionContext(
        variables={
            "API_TOKEN": secret,
        },
        runtime={
            "mode": "realtime",
        },
    )

    plan = plan_system(
        _system(),
        execution_context=context,
    )

    document = plan.model_dump(
        mode="json",
        by_alias=True,
    )

    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
    )

    assert secret not in encoded
    assert "API_TOKEN" not in encoded

    assert (
        document[
            "execution_context_sha256"
        ]
        == system_execution_context_digest(
            context
        )
    )


def test_no_context_preserves_legacy_plan_digest_shape() -> None:
    plan = plan_system(
        _system()
    )

    assert (
        plan.execution_context_sha256
        is None
    )

    legacy_document = plan.model_dump(
        mode="json",
        by_alias=True,
    )

    legacy_document.pop(
        "execution_context_sha256",
        None,
    )
    legacy_document.pop(
        "system_startup",
        None,
    )
    legacy_document.pop(
        "inputs",
        None,
    )
    legacy_document.pop(
        "outputs",
        None,
    )
    legacy_document.pop(
        "parameters",
        None,
    )
    legacy_document.pop(
        "resource_requirements",
        None,
    )
    legacy_document.pop(
        "bindings",
        None,
    )

    encoded = json.dumps(
        legacy_document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    legacy_digest = hashlib.sha256(
        encoded
    ).hexdigest()

    assert (
        system_plan_digest(plan)
        == legacy_digest
    )



def _connected_system_for_edge_policy():
    from nodrix.system import (
        Connection,
        Graph,
        NodeInstance,
        SystemModel,
    )

    return SystemModel(
        name="edge-policy-plan",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="source",
                        uses="demo.source",
                    ),
                    NodeInstance(
                        name="sink",
                        uses="demo.sink",
                    ),
                ),
                connections=(
                    Connection(
                        **{
                            "from": "source.output",
                            "to": "sink.input",
                        }
                    ),
                ),
            ),
        ),
    )


def test_edge_defaults_are_resolved_into_planned_connections() -> None:
    plan = plan_system(
        _connected_system_for_edge_policy(),
        execution_context=_context(
            config_file="mid360s.yaml",
        ),
    )

    connection = (
        plan.graphs[0]
        .connections[0]
    )

    assert (
        connection.execution
        .queue.capacity
        == 1
    )

    assert (
        connection.execution
        .queue.policy
        == "latest"
    )

    assert (
        connection.execution
        .memory.domain
        == "auto"
    )

    assert (
        connection.execution
        .memory.allow_copy
        is True
    )


def test_missing_execution_context_uses_canonical_connection_policy() -> None:
    plan = plan_system(
        _connected_system_for_edge_policy()
    )

    connection = (
        plan.graphs[0]
        .connections[0]
    )

    assert (
        connection.execution
        .queue.capacity
        == 8
    )

    assert (
        connection.execution
        .queue.policy
        == "block"
    )

    assert (
        connection.execution
        .memory.domain
        == "auto"
    )

    assert (
        connection.execution
        .memory.allow_copy
        is True
    )
