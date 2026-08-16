"""Explicit authoring frontend for Nodrix extension bundles.

Extension groups planner and executor implementations for later registration
into a canonical ExtensionRegistry.

It does not create a global registry, perform discovery, plan Operations,
execute Plans, persist Runs, or own runtime state.
"""

from __future__ import annotations

from ..executor_contract import (
    PlanExecutor,
)
from ..extension_registry import (
    ExtensionRegistry,
)
from ..model import (
    OperationKind,
    PlanKind,
)
from ..planner_contract import (
    OperationPlanner,
)


class Extension:
    """Author one explicit bundle of Nodrix extension registrations."""

    def __init__(
        self,
        name: str,
    ) -> None:
        if not isinstance(
            name,
            str,
        ):
            raise TypeError(
                "extension name must be a string"
            )

        normalized = name.strip()

        if not normalized:
            raise ValueError(
                "extension name must be non-empty"
            )

        self._name = normalized

        self._planners: dict[
            OperationKind,
            OperationPlanner,
        ] = {}

        self._executors: dict[
            PlanKind,
            PlanExecutor,
        ] = {}

    @property
    def name(
        self,
    ) -> str:
        return self._name

    @property
    def planners(
        self,
    ) -> tuple[OperationPlanner, ...]:
        """Return planner registrations in stable OperationKind order."""

        return tuple(
            self._planners[kind]
            for kind in sorted(
                self._planners,
                key=lambda item: item.value,
            )
        )

    @property
    def executors(
        self,
    ) -> tuple[
        tuple[
            PlanKind,
            PlanExecutor,
        ],
        ...,
    ]:
        """Return executor registrations in stable PlanKind order."""

        return tuple(
            (
                kind,
                self._executors[kind],
            )
            for kind in sorted(
                self._executors,
                key=lambda item: item.value,
            )
        )

    def add_planner(
        self,
        planner: OperationPlanner,
    ) -> OperationPlanner:
        """Add one canonical OperationPlanner to this bundle."""

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
                "extension already contains a planner "
                f"for operation kind {kind.value!r}: "
                f"{existing.planner_id!r}"
            )

        self._planners[
            kind
        ] = planner

        return planner

    def add_executor(
        self,
        plan_kind: PlanKind | str,
        executor: PlanExecutor,
    ) -> PlanExecutor:
        """Add one canonical PlanExecutor registration to this bundle."""

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
                "extension already contains an executor "
                f"for plan kind {kind.value!r}: "
                f"{existing.executor_id!r}"
            )

        self._executors[
            kind
        ] = executor

        return executor

    def register_into(
        self,
        registry: ExtensionRegistry,
    ) -> None:
        """Register this bundle into one explicit canonical registry.

        Conflicts are checked before any registry mutation so a conflicting
        bundle cannot be installed partially.
        """

        if not isinstance(
            registry,
            ExtensionRegistry,
        ):
            raise TypeError(
                "registry must be an ExtensionRegistry"
            )

        existing_operations = set(
            registry.operation_kinds
        )

        existing_plans = set(
            registry.plan_kinds
        )

        planner_conflicts = tuple(
            kind
            for kind in self._planners
            if kind in existing_operations
        )

        executor_conflicts = tuple(
            kind
            for kind in self._executors
            if kind in existing_plans
        )

        if (
            planner_conflicts
            or executor_conflicts
        ):
            details: list[str] = []

            details.extend(
                "operation "
                f"{kind.value!r}"
                for kind
                in sorted(
                    planner_conflicts,
                    key=lambda item: item.value,
                )
            )

            details.extend(
                "plan "
                f"{kind.value!r}"
                for kind
                in sorted(
                    executor_conflicts,
                    key=lambda item: item.value,
                )
            )

            raise ValueError(
                f"extension {self.name!r} conflicts "
                "with existing registry registrations: "
                + ", ".join(details)
            )

        for planner in self.planners:
            registry.register_planner(
                planner
            )

        for kind, executor in self.executors:
            registry.register_executor(
                kind,
                executor,
            )


__all__ = [
    "Extension",
]
