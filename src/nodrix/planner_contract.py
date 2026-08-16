"""Canonical planning extension contracts for Nodrix.

Planning converts canonical intent into one exact executable plan:

    Operation
        -> PlanningContext
        -> OperationPlanner
        -> PlanRecord

An Operation may already pin its subject revision.  When it does not, revision
resolution is delegated to the PlanningContext through a DefinitionResolver.

The planner itself must not infer project roots, scan storage, inspect the
current working directory, or invent a parallel Definition identity model.

Built-in Nodrix planners may retain domain-specific APIs.  This module defines
the common extension contract for operation-driven planning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .model import (
    DefinitionRecord,
    EntityRef,
    Operation,
    OperationKind,
    PlanRecord,
    RevisionRef,
)


@runtime_checkable
class DefinitionResolver(Protocol):
    """Resolve one canonical EntityRef to a concrete Definition revision."""

    def resolve_definition(
        self,
        entity: EntityRef,
    ) -> DefinitionRecord:
        """Return the DefinitionRecord currently selected for an entity."""
        ...


@dataclass(frozen=True, slots=True)
class PlanningContext:
    """External resolution services available during canonical planning.

    The context owns resolution policy.  An OperationPlanner consumes resolved
    information but must not silently invent its own storage/discovery policy.
    """

    definition_resolver: DefinitionResolver | None = None

    def resolve_definition(
        self,
        operation: Operation,
    ) -> DefinitionRecord:
        """Resolve and validate the Definition targeted by an Operation."""

        if not isinstance(
            operation,
            Operation,
        ):
            raise TypeError(
                "operation must be an Operation"
            )

        resolver = self.definition_resolver

        if resolver is None:
            raise ValueError(
                "planning context has no DefinitionResolver"
            )

        record = resolver.resolve_definition(
            operation.subject
        )

        if not isinstance(
            record,
            DefinitionRecord,
        ):
            raise TypeError(
                "DefinitionResolver must return "
                "a DefinitionRecord"
            )

        if record.entity != operation.subject:
            raise ValueError(
                "resolved Definition must reference "
                "the operation subject"
            )

        pinned = operation.subject_revision

        if (
            pinned is not None
            and record.revision != pinned
        ):
            raise ValueError(
                "resolved Definition revision must match "
                "the revision pinned by the operation"
            )

        return record

    def resolve_subject_revision(
        self,
        operation: Operation,
    ) -> RevisionRef:
        """Return the exact subject revision to use for canonical planning."""

        if not isinstance(
            operation,
            Operation,
        ):
            raise TypeError(
                "operation must be an Operation"
            )

        pinned = operation.subject_revision

        if pinned is not None:
            return pinned

        return self.resolve_definition(
            operation
        ).revision


@runtime_checkable
class OperationPlanner(Protocol):
    """Common extension contract for canonical Operation planners."""

    @property
    def planner_id(self) -> str:
        """Return the stable identifier of this planner."""
        ...

    @property
    def operation_kind(self) -> OperationKind:
        """Return the OperationKind accepted by this planner."""
        ...

    def plan(
        self,
        operation: Operation,
        *,
        context: PlanningContext,
    ) -> PlanRecord:
        """Resolve one canonical Operation into one exact PlanRecord."""
        ...


__all__ = [
    "DefinitionResolver",
    "OperationPlanner",
    "PlanningContext",
]
