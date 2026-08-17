"""Project-level adapters for resolving canonical Nodrix Systems.

The canonical System layer does not know about project Profiles.
This module translates project configuration concepts into generic
System authoring inputs.
"""

from __future__ import annotations

from pathlib import Path

from .project_foundation import (
    ProjectProfileConfig,
    resolve_project_profile_config,
)
from .system.io import (
    SystemLoadResult,
    load_system_details,
)
from .system.source import SystemConfigOverlay


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
    profile: str,
    root: str | Path | None = None,
    format: str | None = None,
) -> SystemLoadResult:
    """Load a System with one explicit project Profile Config overlay."""

    overlay = resolve_project_profile_overlay(
        profile,
        root=root,
    )

    return load_system_details(
        path,
        format=format,
        config_overlays=(
            overlay,
        ),
    )


__all__ = [
    "load_project_system_details",
    "project_profile_config_overlay",
    "resolve_project_profile_overlay",
]
