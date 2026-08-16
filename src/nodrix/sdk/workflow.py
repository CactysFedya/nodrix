"""Public authoring SDK for Nodrix workflow definitions.

The SDK is a frontend for ``nodrix.workflow/v1``.  It does not execute
commands and deliberately does not introduce another workflow runtime.

Documents produced here are consumed by the existing workflow planner and
executor exactly like hand-written YAML workflows.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


WORKFLOW_SCHEMA = "nodrix.workflow/v1"


def _required_string(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} must be non-empty"
        )

    return normalized


def _dependency_names(
    value: str | Iterable[str] | None,
) -> tuple[str, ...]:
    if value is None:
        return ()

    raw = (
        (value,)
        if isinstance(value, str)
        else tuple(value)
    )

    result: list[str] = []
    seen: set[str] = set()

    for item in raw:
        name = _required_string(
            item,
            field_name="workflow dependency",
        )

        if name in seen:
            continue

        seen.add(name)
        result.append(name)

    return tuple(result)


def _merge_dependencies(
    *groups: Iterable[str],
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()

    for group in groups:
        for name in group:
            if name in seen:
                continue

            seen.add(name)
            result.append(name)

    return tuple(result)


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """Handle to one step declared through :class:`Workflow`."""

    id: str
    command: str
    depends_on: tuple[str, ...]
    _workflow: Workflow = field(
        repr=False,
        compare=False,
    )

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical ``nodrix.workflow/v1`` step mapping."""

        result: dict[str, Any] = {
            "id": self.id,
            "run": self.command,
        }

        if self.depends_on:
            result["depends_on"] = list(
                self.depends_on
            )

        return result


class Workflow:
    """Incrementally build one ``nodrix.workflow/v1`` definition."""

    def __init__(
        self,
        name: str,
    ) -> None:
        self._name = _required_string(
            name,
            field_name="workflow name",
        )

        self._steps: list[
            WorkflowStep
        ] = []

        self._step_ids: set[str] = set()

    @property
    def name(self) -> str:
        return self._name

    @property
    def steps(
        self,
    ) -> tuple[WorkflowStep, ...]:
        return tuple(self._steps)

    def _after_dependencies(
        self,
        value: (
            WorkflowStep
            | Iterable[WorkflowStep]
            | None
        ),
    ) -> tuple[str, ...]:
        if value is None:
            return ()

        raw = (
            (value,)
            if isinstance(
                value,
                WorkflowStep,
            )
            else tuple(value)
        )

        result: list[str] = []

        for step in raw:
            if not isinstance(
                step,
                WorkflowStep,
            ):
                raise TypeError(
                    "after must contain "
                    "WorkflowStep objects"
                )

            if step._workflow is not self:
                raise ValueError(
                    "workflow step dependency "
                    "belongs to another workflow"
                )

            result.append(
                step.id
            )

        return tuple(result)

    def run(
        self,
        step_id: str,
        command: str,
        *,
        after: (
            WorkflowStep
            | Iterable[WorkflowStep]
            | None
        ) = None,
        depends_on: (
            str
            | Iterable[str]
            | None
        ) = None,
    ) -> WorkflowStep:
        """Declare one command step.

        ``after`` is the convenient object-reference API.  ``depends_on``
        exposes the native workflow dependency names when that is more useful.
        Both forms may be combined.
        """

        normalized_id = (
            _required_string(
                step_id,
                field_name="workflow step id",
            )
        )

        normalized_command = (
            _required_string(
                command,
                field_name=(
                    f"workflow step "
                    f"{normalized_id!r} command"
                ),
            )
        )

        if normalized_id in self._step_ids:
            raise ValueError(
                "duplicate workflow step id: "
                f"{normalized_id}"
            )

        dependencies = (
            _merge_dependencies(
                _dependency_names(
                    depends_on
                ),
                self._after_dependencies(
                    after
                ),
            )
        )

        unknown = [
            dependency
            for dependency
            in dependencies
            if dependency
            not in self._step_ids
        ]

        if unknown:
            raise ValueError(
                "workflow step "
                f"{normalized_id!r} depends on "
                "unknown or later step(s): "
                + ", ".join(unknown)
            )

        step = WorkflowStep(
            id=normalized_id,
            command=normalized_command,
            depends_on=dependencies,
            _workflow=self,
        )

        self._steps.append(step)
        self._step_ids.add(
            normalized_id
        )

        return step

    def to_dict(self) -> dict[str, Any]:
        """Compile this builder into a canonical workflow definition."""

        return {
            "schema": WORKFLOW_SCHEMA,
            "name": self.name,
            "steps": [
                step.to_dict()
                for step
                in self._steps
            ],
        }


__all__ = [
    "WORKFLOW_SCHEMA",
    "Workflow",
    "WorkflowStep",
]
