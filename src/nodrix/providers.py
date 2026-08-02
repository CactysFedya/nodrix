"""Stable metadata-first Provider API facade.

Discovery, verification, loading, compatibility, and diagnostics are split
into focused modules. Existing ``nodrix.providers`` imports remain stable
throughout Nodrix 2.x.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from .provider_common import (
    CORE_PROVIDER_FEATURES,
    DEFAULT_TRUST_STORE,
    LoadedProvider,
    ProviderCandidate,
    ProviderPolicy,
    ProviderVerification,
)
from .provider_diagnostics import (
    run_provider_probe,
    verify_provider_nodes,
)
from .provider_discovery import (
    _legacy_ros2_probe,
    _legacy_vision_probe,
    discover_providers,
    resolve_provider,
)
from .provider_loading import (
    load_provider,
    load_provider_application,
    load_provider_node,
    load_provider_resource,
    load_provider_session,
    provider_for_application,
    provider_for_link,
    provider_for_node,
    provider_for_resource,
    provider_for_session,
    provider_for_template,
    provider_for_transport,
    provider_template_ids,
    reset_provider_cache,
)
from .provider_templates import create_provider_project as _create_provider_project
from .provider_verification import (
    provider_record,
    provider_records,
    sign_provider_metadata,
    verify_candidate,
    verify_provider,
)


def create_provider_project(
    directory: str | Path,
    template_id: str,
    *,
    force: bool = False,
) -> list[Path]:
    """Compatibility facade for provider-owned project templates."""

    return _create_provider_project(
        directory,
        template_id,
        force=force,
        _resolver=provider_for_template,
        _verifier=verify_candidate,
    )

__all__ = [
    "CORE_PROVIDER_FEATURES",
    "DEFAULT_TRUST_STORE",
    "ProviderCandidate",
    "ProviderPolicy",
    "ProviderVerification",
    "LoadedProvider",
    "discover_providers",
    "resolve_provider",
    "verify_candidate",
    "verify_provider",
    "sign_provider_metadata",
    "provider_record",
    "provider_records",
    "load_provider",
    "load_provider_node",
    "load_provider_session",
    "load_provider_resource",
    "load_provider_application",
    "provider_for_node",
    "provider_for_session",
    "provider_for_resource",
    "provider_for_application",
    "provider_for_link",
    "provider_for_transport",
    "provider_for_template",
    "provider_template_ids",
    "create_provider_project",
    "verify_provider_nodes",
    "run_provider_probe",
    "reset_provider_cache",
    "_legacy_ros2_probe",
    "_legacy_vision_probe",
    "importlib",
]
