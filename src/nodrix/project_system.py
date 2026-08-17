"""Project-level adapters for resolving canonical Nodrix Systems.

The canonical System layer does not know about project Profiles.
This module translates project configuration concepts into generic
System authoring inputs.
"""

from __future__ import annotations

from pathlib import Path

from .profiles import get_runtime_preset
from .project_foundation import (
    ProjectProfileConfig,
    resolve_project_profile_config,
    resolve_project_resource,
)
from .system.execution_context import (
    SystemExecutionContext,
)
from .system.io import (
    SystemLoadResult,
    load_system_details,
)
from .system.source import SystemConfigOverlay
from .workspace import ProjectExecutionContext


def system_execution_context_from_project(
    context: ProjectExecutionContext,
) -> SystemExecutionContext:
    """Translate project execution selection into effective System semantics."""

    if not isinstance(
        context,
        ProjectExecutionContext,
    ):
        raise TypeError(
            "context must be a ProjectExecutionContext"
        )

    preset = get_runtime_preset(
        context.runtime_preset
    )

    return SystemExecutionContext(
        variables=dict(
            context.variables
        ),
        sources=tuple(
            str(source)
            for source in context.sources
        ),
        runtime=dict(
            preset.get("runtime")
            or {}
        ),
        node_defaults=dict(
            preset.get("node_defaults")
            or {}
        ),
        edge_defaults=dict(
            preset.get("edge_defaults")
            or {}
        ),
        stream_defaults=dict(
            preset.get("stream_defaults")
            or {}
        ),
    )


def project_profile_config_overlay(
    profile: ProjectProfileConfig,
) -> SystemConfigOverlay:
    """Translate one project Profile into a generic System Config overlay."""

    return SystemConfigOverlay(
        config=profile.config,
        source=profile.path,
    )


def resolve_project_profile_overlay(
    name: str,
    *,
    root: str | Path | None = None,
) -> SystemConfigOverlay:
    """Resolve one explicit project Profile as a System Config overlay."""

    profile = resolve_project_profile_config(
        name,
        root=root,
    )

    return project_profile_config_overlay(
        profile
    )


def load_project_system_details(
    path: str | Path,
    *,
    profile: str | None = None,
    root: str | Path | None = None,
    format: str | None = None,
) -> SystemLoadResult:
    """Load one project System with project-local authoring resolution.

    Project System names in ``systems[*].uses`` are authoring aliases.
    They resolve through the project's registered ``systems`` section and
    become immutable child System RevisionRefs before canonical validation.

    An optional Project Profile contributes only its semantic System Config
    overlay here; execution-context semantics remain a separate boundary.
    """

    system_path = Path(
        path
    ).expanduser().resolve()

    resolver_root = (
        Path(root).expanduser().resolve()
        if root is not None
        else system_path.parent
    )

    overlays: tuple[
        SystemConfigOverlay,
        ...,
    ] = ()

    if profile is not None:
        overlays = (
            resolve_project_profile_overlay(
                profile,
                root=resolver_root,
            ),
        )

    def resolve_child_system(
        reference: str,
    ) -> Path:
        return resolve_project_resource(
            "system",
            reference,
            root=resolver_root,
        ).path

    return load_system_details(
        system_path,
        format=format,
        config_overlays=overlays,
        child_system_resolver=(
            resolve_child_system
        ),
    )


__all__ = [
    "load_project_system_details",
    "project_profile_config_overlay",
    "resolve_project_profile_overlay",
    "system_execution_context_from_project",
]
