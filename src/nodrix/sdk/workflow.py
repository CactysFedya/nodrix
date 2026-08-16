"""Public authoring SDK for Nodrix workflow definitions.

The SDK is a frontend for ``nodrix.workflow/v1``. It does not plan or execute
commands and deliberately does not introduce another workflow runtime.

Documents produced here are consumed by the existing workflow planner and
executor exactly like hand-written YAML workflows.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ..workflow_schema import WORKFLOW_SCHEMA


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


def _optional_string(
    value: object | None,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    return _required_string(
        value,
        field_name=field_name,
    )


def _environment_mapping(
    value: Mapping[str, Any] | None,
    *,
    field_name: str,
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})

    if not isinstance(
        value,
        Mapping,
    ):
        raise TypeError(
            f"{field_name} must be a mapping"
        )

    return MappingProxyType(
        {
            str(key): str(item)
            for key, item
            in value.items()
        }
    )


def _definition_value(
    value: (
        bool
        | Mapping[str, Any]
        | None
    ),
    *,
    field_name: str,
) -> bool | Mapping[str, Any] | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if not isinstance(
        value,
        Mapping,
    ):
        raise TypeError(
            f"{field_name} must be "
            "a mapping, boolean or None"
        )

    return MappingProxyType(
        deepcopy(
            dict(value)
        )
    )


def _materialize_definition_value(
    value: (
        bool
        | Mapping[str, Any]
        | None
    ),
) -> bool | dict[str, Any] | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    return deepcopy(
        dict(value)
    )


def _timeout_value(
    value: int | float | None,
) -> float | None:
    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(
        value,
        (int, float),
    ):
        raise TypeError(
            "timeout_seconds must be "
            "a number or None"
        )

    return float(value)


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
            field_name=(
                "workflow dependency"
            ),
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

    recipe: str | None = None
    cwd: str = "."

    environment: Mapping[str, str] = field(
        default_factory=dict,
        repr=False,
    )

    when: (
        bool
        | Mapping[str, Any]
        | None
    ) = field(
        default=None,
        repr=False,
    )

    timeout_seconds: float | None = None
    continue_on_error: bool = False

    cache: (
        bool
        | Mapping[str, Any]
        | None
    ) = field(
        default=None,
        repr=False,
    )

    def to_dict(self) -> dict[str, Any]:
        """Return the corresponding ``nodrix.workflow/v1`` step mapping."""

        result: dict[str, Any] = {
            "id": self.id,
            "run": self.command,
        }

        if self.depends_on:
            result["depends_on"] = list(
                self.depends_on
            )

        if self.recipe is not None:
            result["recipe"] = (
                self.recipe
            )

        if self.cwd != ".":
            result["cwd"] = self.cwd

        if self.environment:
            result["environment"] = dict(
                self.environment
            )

        if self.when is not None:
            result["when"] = (
                _materialize_definition_value(
                    self.when
                )
            )

        if self.timeout_seconds is not None:
            result["timeout_seconds"] = (
                self.timeout_seconds
            )

        if self.continue_on_error:
            result["continue_on_error"] = (
                True
            )

        if self.cache is not None:
            result["cache"] = (
                _materialize_definition_value(
                    self.cache
                )
            )

        return result


class Workflow:
    """Incrementally build one ``nodrix.workflow/v1`` definition."""

    def __init__(
        self,
        name: str,
        *,
        implements: str | None = None,
        environment: (
            Mapping[str, Any]
            | None
        ) = None,
    ) -> None:
        self._name = _required_string(
            name,
            field_name="workflow name",
        )

        self._implements = _optional_string(
            implements,
            field_name="workflow implements",
        )

        self._environment = (
            _environment_mapping(
                environment,
                field_name=(
                    "workflow environment"
                ),
            )
        )

        self._steps: list[
            WorkflowStep
        ] = []

        self._step_ids: set[str] = set()

    @property
    def name(self) -> str:
        return self._name

    @property
    def implements(self) -> str | None:
        return self._implements

    @property
    def environment(
        self,
    ) -> Mapping[str, str]:
        return self._environment

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
        recipe: str | None = None,
        cwd: str = ".",
        environment: (
            Mapping[str, Any]
            | None
        ) = None,
        when: (
            bool
            | Mapping[str, Any]
            | None
        ) = None,
        timeout_seconds: (
            int
            | float
            | None
        ) = None,
        continue_on_error: bool = False,
        cache: (
            bool
            | Mapping[str, Any]
            | None
        ) = None,
    ) -> WorkflowStep:
        """Declare one command step.

        ``after`` is the convenient object-reference dependency API.
        ``depends_on`` exposes the native workflow dependency names.

        Other arguments map directly to fields of ``nodrix.workflow/v1``.
        Their runtime semantics remain owned by the existing workflow
        planner and executor.
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

        if not isinstance(
            continue_on_error,
            bool,
        ):
            raise TypeError(
                "continue_on_error "
                "must be a boolean"
            )

        step = WorkflowStep(
            id=normalized_id,
            command=normalized_command,
            depends_on=dependencies,
            recipe=_optional_string(
                recipe,
                field_name=(
                    f"workflow step "
                    f"{normalized_id!r} recipe"
                ),
            ),
            cwd=_required_string(
                cwd,
                field_name=(
                    f"workflow step "
                    f"{normalized_id!r} cwd"
                ),
            ),
            environment=(
                _environment_mapping(
                    environment,
                    field_name=(
                        f"workflow step "
                        f"{normalized_id!r} "
                        "environment"
                    ),
                )
            ),
            when=_definition_value(
                when,
                field_name=(
                    f"workflow step "
                    f"{normalized_id!r} when"
                ),
            ),
            timeout_seconds=(
                _timeout_value(
                    timeout_seconds
                )
            ),
            continue_on_error=(
                continue_on_error
            ),
            cache=_definition_value(
                cache,
                field_name=(
                    f"workflow step "
                    f"{normalized_id!r} cache"
                ),
            ),
            _workflow=self,
        )

        self._steps.append(step)
        self._step_ids.add(
            normalized_id
        )

        return step

    def to_dict(self) -> dict[str, Any]:
        """Compile this builder into a canonical workflow definition."""

        result: dict[str, Any] = {
            "schema": WORKFLOW_SCHEMA,
            "name": self.name,
        }

        if self.implements is not None:
            result["implements"] = self.implements

        if self.environment:
            result["environment"] = dict(
                self.environment
            )

        result["steps"] = [
            step.to_dict()
            for step
            in self._steps
        ]

        return result


__all__ = [
    "WORKFLOW_SCHEMA",
    "Workflow",
    "WorkflowStep",
]
