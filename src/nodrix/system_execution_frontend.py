"""Reusable control-plane construction for canonical System execution.

This module connects an already-resolved SystemExecutionPlan to concrete
ExecutionBackend instances without knowing how those backends are discovered or
configured.

The frontend is intentionally backend-neutral:

* no LocalBackend dependency;
* no CLI dependency;
* no YAML/project/profile resolution;
* no Benchmark dependency.

Unsupported scopes remain unbound. SystemOrchestrator then reports its canonical
ORCH101 diagnostic instead of this layer inventing fallback behavior.
"""

from __future__ import annotations

from typing import Callable

from .model import (
    SYSTEM_EXECUTION,
    PlanRecord,
)
from .system import (
    ExecutionBackend,
    ExecutionScope,
    SystemExecutionPlan,
    SystemOrchestrator,
    plan_execution_scopes,
)


SystemExecutionPlanInput = (
    SystemExecutionPlan
    | PlanRecord
)

SystemBackendFactory = Callable[
    [
        ExecutionScope,
    ],
    ExecutionBackend | None,
]


def system_execution_plan(
    value: SystemExecutionPlanInput,
) -> SystemExecutionPlan:
    """Return the exact domain SystemExecutionPlan behind an execution input.

    Canonical frontends often carry PlanRecord while orchestration operates on
    the domain plan. Keeping this normalization in one place avoids every CLI,
    Benchmark runner or future service endpoint reimplementing the same
    validation.
    """

    if isinstance(
        value,
        SystemExecutionPlan,
    ):
        return value

    if not isinstance(
        value,
        PlanRecord,
    ):
        raise TypeError(
            "value must be a SystemExecutionPlan "
            "or PlanRecord"
        )

    if (
        value.kind
        != SYSTEM_EXECUTION
    ):
        raise ValueError(
            "PlanRecord must have "
            "system-execution kind"
        )

    payload = value.payload

    if not isinstance(
        payload,
        SystemExecutionPlan,
    ):
        raise TypeError(
            "system-execution PlanRecord payload "
            "must be a SystemExecutionPlan"
        )

    return payload


def hierarchical_execution_scopes(
    value: SystemExecutionPlanInput,
) -> tuple[
    ExecutionScope,
    ...,
]:
    """Return unique execution scopes across the complete System plan tree.

    Traversal order is deterministic: direct scopes keep planner order, then
    child Systems are visited in declared/planned order.

    The ``seen`` set prevents duplicate backend construction when parent and
    child Systems use the same target/backend pair.
    """

    root = system_execution_plan(
        value
    )

    result: list[
        ExecutionScope
    ] = []

    seen: set[
        ExecutionScope
    ] = set()

    def visit(
        current: SystemExecutionPlan,
    ) -> None:
        for scope in plan_execution_scopes(
            current
        ):
            if scope in seen:
                continue

            seen.add(
                scope
            )

            result.append(
                scope
            )

        for child in current.systems:
            visit(
                child.plan
            )

    visit(
        root
    )

    return tuple(
        result
    )


def build_system_orchestrator(
    value: SystemExecutionPlanInput,
    *,
    backend_factory: SystemBackendFactory,
) -> SystemOrchestrator:
    """Build one orchestrator from explicit per-scope backend resolution.

    ``None`` deliberately means "no binding for this scope". It is not an
    error or fallback at this layer: SystemOrchestrator owns canonical
    validation and will surface ORCH101.

    Likewise, backend-id mismatches are preserved for SystemOrchestrator to
    report as ORCH102 rather than being translated into a second error model.
    """

    if not callable(
        backend_factory
    ):
        raise TypeError(
            "backend_factory must be callable"
        )

    bindings: dict[
        ExecutionScope,
        ExecutionBackend,
    ] = {}

    for scope in hierarchical_execution_scopes(
        value
    ):
        backend = backend_factory(
            scope
        )

        if backend is None:
            continue

        if not isinstance(
            backend,
            ExecutionBackend,
        ):
            raise TypeError(
                "backend_factory must return "
                "ExecutionBackend or None"
            )

        bindings[
            scope
        ] = backend

    return SystemOrchestrator(
        bindings
    )


__all__ = [
    "SystemBackendFactory",
    "SystemExecutionPlanInput",
    "build_system_orchestrator",
    "hierarchical_execution_scopes",
    "system_execution_plan",
]
