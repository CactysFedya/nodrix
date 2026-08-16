"""Registry for canonical Nodrix planning and execution extensions.

The registry connects two already-defined extension contracts:

    OperationKind -> OperationPlanner
    PlanKind      -> PlanExecutor

It deliberately performs registration and lookup only.

Planning remains owned by OperationPlanner.
Execution remains owned by PlanExecutor.
Definition resolution remains owned by PlanningContext.
Run persistence remains owned by the Operation boundary.

This module does not perform package discovery and does not expose a global
mutable registry.
"""

from __future__ import annotations

from .executor_contract import PlanExecutor
from .model import (
    OperationKind,
    PlanKind,
)
from .planner_contract import OperationPlanner


class ExtensionRegistry:
    """Explicit registry of canonical Nodrix planners and executors."""

    def __init__(self) -> None:
        self._planners: dict[
            OperationKind,
            OperationPlanner,
        ] = {}

        self._executors: dict[
            PlanKind,
            PlanExecutor,
        ] = {}

    @property
    def operation_kinds(
        self,
    ) -> tuple[OperationKind, ...]:
        """Return registered Operation kinds in stable order."""

        return tuple(
            sorted(
                self._planners,
                key=lambda item: item.value,
            )
        )

    @property
    def plan_kinds(
        self,
    ) -> tuple[PlanKind, ...]:
        """Return registered Plan kinds in stable order."""

        return tuple(
            sorted(
                self._executors,
                key=lambda item: item.value,
            )
        )

    def register_planner(
        self,
        planner: OperationPlanner,
    ) -> None:
        """Register one planner for its declared OperationKind."""

        if not isinstance(
            planner,
            OperationPlanner,
        ):
            raise TypeError(
                "planner must satisfy OperationPlanner"
            )

        kind = OperationKind.parse(
            planner.operation_kind
        )

        if kind in self._planners:
            existing = self._planners[
                kind
            ]

            raise ValueError(
                "planner already registered for "
                f"operation kind {kind.value!r}: "
                f"{existing.planner_id!r}"
            )

        self._planners[
            kind
        ] = planner

    def register_executor(
        self,
        plan_kind: PlanKind | str,
        executor: PlanExecutor,
    ) -> None:
        """Register one executor for one canonical PlanKind."""

        kind = PlanKind.parse(
            plan_kind
        )

        if not isinstance(
            executor,
            PlanExecutor,
        ):
            raise TypeError(
                "executor must satisfy PlanExecutor"
            )

        if kind in self._executors:
            existing = self._executors[
                kind
            ]

            raise ValueError(
                "executor already registered for "
                f"plan kind {kind.value!r}: "
                f"{existing.executor_id!r}"
            )

        self._executors[
            kind
        ] = executor

    def planner_for(
        self,
        operation_kind: (
            OperationKind
            | str
        ),
    ) -> OperationPlanner:
        """Return the planner registered for an OperationKind."""

        kind = OperationKind.parse(
            operation_kind
        )

        try:
            return self._planners[
                kind
            ]
        except KeyError as exc:
            raise KeyError(
                "no planner registered for "
                f"operation kind {kind.value!r}"
            ) from exc

    def executor_for(
        self,
        plan_kind: (
            PlanKind
            | str
        ),
    ) -> PlanExecutor:
        """Return the executor registered for a PlanKind."""

        kind = PlanKind.parse(
            plan_kind
        )

        try:
            return self._executors[
                kind
            ]
        except KeyError as exc:
            raise KeyError(
                "no executor registered for "
                f"plan kind {kind.value!r}"
            ) from exc


__all__ = [
    "ExtensionRegistry",
]
