"""Resolved canonical System workloads shared by execution frontends.

This module belongs to the authoring/control-plane layer above ``nodrix.system``.
The canonical System model deliberately does not know about projects or Project
Profiles.

A resolved workload freezes the semantic inputs needed to execute one System:
the resolved Definition, optional execution context and exact canonical Plan.
Live backend/orchestrator state is intentionally not stored here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .model import (
    PlanRecord,
)
from .project_system import (
    load_project_system_details,
    system_execution_context_from_project,
)
from .workspace import (
    find_workspace,
    resolve_project_execution_context,
)
from .system import (
    DefinitionCatalog,
    SystemExecutionContext,
    SystemModel,
    load_system_details,
)
from .system.canonical import (
    plan_canonical_system,
)


SystemCatalogProvider = Callable[
    [
        Path | None,
    ],
    DefinitionCatalog | None,
]


@dataclass(
    frozen=True,
    slots=True,
)
class ResolvedSystemWorkload:
    """Immutable semantic inputs of one canonical System execution."""

    source: Path
    project_root: Path | None
    profile: str | None
    system_definition: SystemModel
    execution_context: (
        SystemExecutionContext | None
    )
    plan: PlanRecord

    def __post_init__(
        self,
    ) -> None:
        source = (
            Path(
                self.source
            )
            .expanduser()
            .resolve()
        )

        object.__setattr__(
            self,
            "source",
            source,
        )

        if not source.is_file():
            raise FileNotFoundError(
                f"System source does not exist: {source}"
            )

        project_root = (
            None
            if self.project_root is None
            else (
                Path(
                    self.project_root
                )
                .expanduser()
                .resolve()
            )
        )

        object.__setattr__(
            self,
            "project_root",
            project_root,
        )

        if (
            self.profile is not None
            and not self.profile.strip()
        ):
            raise ValueError(
                "profile must be non-empty or None"
            )

        if not isinstance(
            self.system_definition,
            SystemModel,
        ):
            raise TypeError(
                "system_definition must be "
                "a SystemModel"
            )

        if (
            self.execution_context
            is not None
            and not isinstance(
                self.execution_context,
                SystemExecutionContext,
            )
        ):
            raise TypeError(
                "execution_context must be a "
                "SystemExecutionContext or None"
            )

        if not isinstance(
            self.plan,
            PlanRecord,
        ):
            raise TypeError(
                "plan must be a PlanRecord"
            )


def resolve_system_workload(
    path: str | Path,
    *,
    profile: str | None = None,
    catalog_provider: (
        SystemCatalogProvider | None
    ) = None,
) -> ResolvedSystemWorkload:
    """Resolve authoring inputs into one exact canonical System workload.

    Project Profile is intentionally an authoring concept.  It is resolved
    here into two independent semantic products:

    * a generic System Config overlay applied while loading the Definition;
    * a materialized SystemExecutionContext bound into the canonical Plan.

    No runtime/backend object is created by this function, which makes the
    result safe to cache and reuse across repeated executions.
    """

    source = (
        Path(
            path
        )
        .expanduser()
        .resolve()
    )

    if not source.is_file():
        raise FileNotFoundError(
            f"System source does not exist: {source}"
        )

    if (
        profile is not None
        and not isinstance(
            profile,
            str,
        )
    ):
        raise TypeError(
            "profile must be a string or None"
        )

    normalized_profile = (
        profile.strip()
        if profile is not None
        else None
    )

    if normalized_profile == "":
        raise ValueError(
            "profile must be non-empty or None"
        )

    project_root = (
        find_workspace(
            source.parent
        )
    )

    if (
        normalized_profile is not None
        and project_root is None
    ):
        raise LookupError(
            "Project Profile requires the System "
            "to belong to a Nodrix project "
            "containing nodrix.yaml"
        )

    # Mirror the canonical System CLI authoring semantics, but through public
    # project/System APIs rather than importing CLI-private helpers.
    if project_root is None:
        details = (
            load_system_details(
                source
            )
        )
    else:
        details = (
            load_project_system_details(
                source,
                profile=normalized_profile,
                root=project_root,
            )
        )

    if normalized_profile is None:
        execution_context = None
    else:
        assert project_root is not None

        project_context = (
            resolve_project_execution_context(
                project_root,
                profile=normalized_profile,
            )
        )

        execution_context = (
            system_execution_context_from_project(
                project_context
            )
        )

    catalog = (
        catalog_provider(
            project_root
        )
        if catalog_provider is not None
        else None
    )

    if (
        catalog is not None
        and not isinstance(
            catalog,
            DefinitionCatalog,
        )
    ):
        raise TypeError(
            "catalog_provider must return "
            "DefinitionCatalog or None"
        )

    system = details.system

    child_definitions = dict(
        details
        .resolution
        .child_system_definitions
    )

    def resolve_child_system(
        revision,
    ):
        return child_definitions.get(
            revision.canonical
        )

    plan = plan_canonical_system(
        system,
        catalog=catalog,
        execution_context=(
            execution_context
        ),
        system_resolver=(
            resolve_child_system
            if system.systems
            else None
        ),
    )

    return ResolvedSystemWorkload(
        source=source,
        project_root=project_root,
        profile=normalized_profile,
        system_definition=system,
        execution_context=(
            execution_context
        ),
        plan=plan,
    )


__all__ = [
    "ResolvedSystemWorkload",
    "SystemCatalogProvider",
    "resolve_system_workload",
]
