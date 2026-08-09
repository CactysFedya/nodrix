"""Trusted provider loading and typed descriptor resolution."""

from __future__ import annotations

import importlib
import os
from typing import Any, Iterable, Mapping

from .errors import ProviderError
from .provider_api import (
    ApplicationDescriptor,
    LinkDescriptor,
    NodeDescriptor,
    ProviderRuntime,
    ResourceDescriptor,
    SessionDescriptor,
    TemplateDescriptor,
    TransportDescriptor,
)
from .provider_common import (
    _DISCOVERY_CACHE,
    _PROVIDER_CACHE_LOCK,
    LoadedProvider,
    ProviderCandidate,
    ProviderPolicy,
)

from .provider_discovery import discover_providers, resolve_provider
from .provider_verification import verify_candidate

def _load_symbol(reference: str) -> Any:
    module_name, symbol_name = reference.split(":", 1)
    value: Any = importlib.import_module(module_name)
    for part in symbol_name.split("."):
        value = getattr(value, part)
    return value


def _runtime_from_entry_point(candidate: ProviderCandidate) -> ProviderRuntime:
    if candidate.entry_point is None:
        return ProviderRuntime(provider_id=candidate.id)
    value = candidate.entry_point.load()
    if isinstance(value, ProviderRuntime):
        runtime = value
    else:
        produced = value() if callable(value) else value
        if produced is None:
            runtime = ProviderRuntime(provider_id=candidate.id)
        elif isinstance(produced, ProviderRuntime):
            runtime = produced
        elif isinstance(produced, Mapping):
            runtime = ProviderRuntime(
                provider_id=str(
                    produced.get("provider_id", candidate.id)
                ),
                nodes=dict(produced.get("nodes") or {}),
                probes=dict(produced.get("probes") or {}),
                sessions=dict(produced.get("sessions") or {}),
                resources=dict(produced.get("resources") or {}),
                applications=dict(produced.get("applications") or {}),
            )
        else:
            try:
                runtime = ProviderRuntime(
                    provider_id=str(produced.provider_id),
                    nodes=dict(produced.nodes),
                    probes=dict(produced.probes),
                    sessions=dict(getattr(produced, "sessions", {})),
                    resources=dict(getattr(produced, "resources", {})),
                    applications=dict(getattr(produced, "applications", {})),
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise ProviderError(
                    f"Provider {candidate.id!r} entry point returned an "
                    "unsupported runtime object"
                ) from exc
    if runtime.provider_id != candidate.id:
        raise ProviderError(
            f"Provider runtime id {runtime.provider_id!r} does not match "
            f"metadata id {candidate.id!r}"
        )
    assert candidate.manifest is not None
    declared_nodes = {item.id for item in candidate.manifest.nodes}
    declared_probes = {item.id for item in candidate.manifest.probes}
    declared_sessions = {item.id for item in candidate.manifest.sessions}
    declared_resources = {item.id for item in candidate.manifest.resources}
    declared_applications = {item.id for item in candidate.manifest.applications}
    undeclared_nodes = sorted(set(runtime.nodes) - declared_nodes)
    undeclared_probes = sorted(set(runtime.probes) - declared_probes)
    undeclared_sessions = sorted(set(runtime.sessions) - declared_sessions)
    undeclared_resources = sorted(set(runtime.resources) - declared_resources)
    undeclared_applications = sorted(
        set(runtime.applications) - declared_applications
    )
    if (
        undeclared_nodes
        or undeclared_probes
        or undeclared_sessions
        or undeclared_resources
        or undeclared_applications
    ):
        raise ProviderError(
            "Provider runtime attempted to register undeclared ids; "
            f"nodes={undeclared_nodes}, probes={undeclared_probes}, "
            f"sessions={undeclared_sessions}, resources={undeclared_resources}, "
            f"applications={undeclared_applications}"
        )
    return runtime


_LOADED_PROVIDERS: dict[tuple[str, str], LoadedProvider] = {}
_DEVELOPMENT_PROVIDERS: dict[str, LoadedProvider] = {}


def register_development_provider(
    manifest,
    runtime: ProviderRuntime,
) -> LoadedProvider:
    """Register an in-memory provider for local development only.

    Development providers deliberately bypass installed-distribution discovery,
    but they still use the canonical ProviderManifest/ProviderRuntime contracts.
    They are never accepted through a production ProviderPolicy.
    """

    provider_id = manifest.metadata.id
    if runtime.provider_id != provider_id:
        raise ProviderError(
            f"Development provider runtime id {runtime.provider_id!r} does not "
            f"match metadata id {provider_id!r}"
        )
    declared_nodes = {item.id for item in manifest.nodes}
    declared_resources = {item.id for item in manifest.resources}
    undeclared_nodes = sorted(set(runtime.nodes) - declared_nodes)
    undeclared_resources = sorted(set(runtime.resources) - declared_resources)
    if undeclared_nodes or undeclared_resources:
        raise ProviderError(
            "Development provider runtime registered undeclared ids; "
            f"nodes={undeclared_nodes}, resources={undeclared_resources}"
        )
    document = manifest.to_dict()
    candidate = ProviderCandidate(
        id=provider_id,
        distribution="local-development",
        distribution_version=manifest.metadata.version,
        manifest=manifest,
        document=document,
        entry_point=None,
        metadata_path=None,
        signature_path=None,
        internal=True,
    )
    verification = verify_candidate(
        candidate,
        policy=ProviderPolicy(production=False),
    )
    if verification.errors:
        raise ProviderError(
            f"Development provider {provider_id!r} was rejected: "
            + "; ".join(verification.errors)
        )
    loaded = LoadedProvider(
        candidate=candidate,
        runtime=runtime,
        verification=verification,
    )
    with _PROVIDER_CACHE_LOCK:
        _DEVELOPMENT_PROVIDERS[provider_id] = loaded
    return loaded


def unregister_development_provider(provider_id: str) -> None:
    with _PROVIDER_CACHE_LOCK:
        _DEVELOPMENT_PROVIDERS.pop(provider_id, None)


def clear_development_providers() -> None:
    with _PROVIDER_CACHE_LOCK:
        _DEVELOPMENT_PROVIDERS.clear()


def _provider_candidates(*, include_legacy: bool) -> tuple[ProviderCandidate, ...]:
    with _PROVIDER_CACHE_LOCK:
        development = tuple(item.candidate for item in _DEVELOPMENT_PROVIDERS.values())
        development_ids = frozenset(_DEVELOPMENT_PROVIDERS)
    installed = tuple(
        candidate
        for candidate in discover_providers(include_legacy=include_legacy)
        if candidate.id not in development_ids
    )
    return (*development, *installed)


def reset_provider_cache() -> None:
    """Clear process-local imports; intended for installers and tests."""

    with _PROVIDER_CACHE_LOCK:
        _LOADED_PROVIDERS.clear()
        _DEVELOPMENT_PROVIDERS.clear()
        _DISCOVERY_CACHE.clear()


def load_provider(
    provider_id: str,
    *,
    policy: ProviderPolicy | None = None,
    include_legacy: bool = True,
    paths: Iterable[str | os.PathLike[str]] | None = None,
) -> LoadedProvider:
    selected_policy = policy or ProviderPolicy.from_environment()
    with _PROVIDER_CACHE_LOCK:
        development = _DEVELOPMENT_PROVIDERS.get(provider_id)
    if development is not None:
        if selected_policy.production:
            raise ProviderError(
                f"Development provider {provider_id!r} is not available in production"
            )
        return development
    candidate = resolve_provider(
        provider_id,
        include_legacy=include_legacy,
        paths=paths,
    )
    verification = verify_candidate(candidate, policy=selected_policy)
    if verification.errors:
        raise ProviderError(
            f"Provider {candidate.id!r} was rejected: "
            + "; ".join(verification.errors)
        )
    key = (candidate.id, verification.metadata_sha256 or "internal")
    with _PROVIDER_CACHE_LOCK:
        cached = _LOADED_PROVIDERS.get(key)
        if cached is not None:
            return cached
        try:
            runtime = _runtime_from_entry_point(candidate)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"Cannot import provider {candidate.id!r}: {exc}"
            ) from exc
        loaded = LoadedProvider(
            candidate=candidate,
            runtime=runtime,
            verification=verification,
        )
        _LOADED_PROVIDERS[key] = loaded
        return loaded


def provider_for_node(
    node_id: str,
    *,
    include_legacy: bool = False,
) -> tuple[ProviderCandidate, NodeDescriptor] | None:
    matches: list[tuple[ProviderCandidate, NodeDescriptor]] = []
    for candidate in _provider_candidates(include_legacy=include_legacy):
        if candidate.manifest is None:
            continue
        for descriptor in candidate.manifest.nodes:
            if descriptor.id == node_id:
                matches.append((candidate, descriptor))
    if not matches:
        return None
    if len(matches) != 1:
        providers = ", ".join(candidate.id for candidate, _ in matches)
        raise ProviderError(
            f"Node id {node_id!r} is declared by multiple providers: "
            f"{providers}"
        )
    candidate, descriptor = matches[0]
    if candidate.error:
        raise ProviderError(
            f"Provider {candidate.id!r} was rejected: {candidate.error}"
        )
    return candidate, descriptor


def load_provider_node(node_id: str) -> type[Any] | None:
    resolved = provider_for_node(node_id, include_legacy=False)
    if resolved is None:
        return None
    candidate, descriptor = resolved
    loaded = load_provider(candidate.id, include_legacy=False)
    value = loaded.runtime.nodes.get(node_id)
    if value is None:
        value = _load_symbol(descriptor.factory)
    if not isinstance(value, type):
        raise ProviderError(
            f"Provider node factory {descriptor.factory!r} did not resolve "
            "to a class"
        )
    return value


def provider_for_session(
    session_id: str,
    *,
    include_legacy: bool = False,
) -> tuple[ProviderCandidate, SessionDescriptor] | None:
    matches: list[tuple[ProviderCandidate, SessionDescriptor]] = []
    for candidate in discover_providers(include_legacy=include_legacy):
        if candidate.manifest is None:
            continue
        for descriptor in candidate.manifest.sessions:
            if descriptor.id == session_id:
                matches.append((candidate, descriptor))
    if not matches:
        return None
    if len(matches) != 1:
        providers = ", ".join(candidate.id for candidate, _ in matches)
        raise ProviderError(
            f"Session id {session_id!r} is declared by multiple providers: "
            f"{providers}"
        )
    candidate, descriptor = matches[0]
    if candidate.error:
        raise ProviderError(
            f"Provider {candidate.id!r} was rejected: {candidate.error}"
        )
    return candidate, descriptor


def load_provider_session(session_id: str) -> type[Any] | None:
    resolved = provider_for_session(session_id, include_legacy=False)
    if resolved is None:
        return None
    candidate, descriptor = resolved
    loaded = load_provider(candidate.id, include_legacy=False)
    value = loaded.runtime.sessions.get(session_id)
    if value is None:
        value = _load_symbol(descriptor.factory)
    if not isinstance(value, type):
        raise ProviderError(
            f"Provider session factory {descriptor.factory!r} did not resolve "
            "to a class"
        )
    return value


def provider_for_resource(
    resource_id: str,
    *,
    include_legacy: bool = False,
) -> tuple[ProviderCandidate, ResourceDescriptor] | None:
    matches: list[tuple[ProviderCandidate, ResourceDescriptor]] = []
    for candidate in _provider_candidates(include_legacy=include_legacy):
        if candidate.manifest is None:
            continue
        for descriptor in candidate.manifest.resources:
            if descriptor.id == resource_id:
                matches.append((candidate, descriptor))
    if not matches:
        return None
    if len(matches) != 1:
        providers = ", ".join(candidate.id for candidate, _ in matches)
        raise ProviderError(
            f"Resource id {resource_id!r} is declared by multiple providers: "
            f"{providers}"
        )
    candidate, descriptor = matches[0]
    if candidate.error:
        raise ProviderError(
            f"Provider {candidate.id!r} was rejected: {candidate.error}"
        )
    return candidate, descriptor


def load_provider_resource(resource_id: str) -> type[Any] | None:
    resolved = provider_for_resource(resource_id, include_legacy=False)
    if resolved is None:
        return None
    candidate, descriptor = resolved
    loaded = load_provider(candidate.id, include_legacy=False)
    value = loaded.runtime.resources.get(resource_id)
    if value is None:
        value = _load_symbol(descriptor.factory)
    if not isinstance(value, type):
        raise ProviderError(
            f"Provider resource factory {descriptor.factory!r} did not "
            "resolve to a class"
        )
    return value


def provider_for_application(
    application_id: str,
    *,
    include_legacy: bool = False,
) -> tuple[ProviderCandidate, ApplicationDescriptor] | None:
    matches: list[tuple[ProviderCandidate, ApplicationDescriptor]] = []
    for candidate in discover_providers(include_legacy=include_legacy):
        if candidate.manifest is None:
            continue
        for descriptor in candidate.manifest.applications:
            if descriptor.id == application_id:
                matches.append((candidate, descriptor))
    if not matches:
        return None
    if len(matches) != 1:
        providers = ", ".join(candidate.id for candidate, _ in matches)
        raise ProviderError(
            f"Application id {application_id!r} is declared by multiple "
            f"providers: {providers}"
        )
    candidate, descriptor = matches[0]
    if candidate.error:
        raise ProviderError(
            f"Provider {candidate.id!r} was rejected: {candidate.error}"
        )
    return candidate, descriptor


def load_provider_application(application_id: str) -> type[Any] | None:
    resolved = provider_for_application(application_id, include_legacy=False)
    if resolved is None:
        return None
    candidate, descriptor = resolved
    loaded = load_provider(candidate.id, include_legacy=False)
    value = loaded.runtime.applications.get(application_id)
    if value is None:
        value = _load_symbol(descriptor.factory)
    if not isinstance(value, type):
        raise ProviderError(
            f"Provider application factory {descriptor.factory!r} did not "
            "resolve to a class"
        )
    return value


def provider_for_link(
    link_id: str,
    *,
    include_legacy: bool = False,
) -> tuple[ProviderCandidate, LinkDescriptor] | None:
    matches: list[tuple[ProviderCandidate, LinkDescriptor]] = []
    for candidate in discover_providers(include_legacy=include_legacy):
        if candidate.manifest is None:
            continue
        for descriptor in candidate.manifest.links:
            if descriptor.id == link_id:
                matches.append((candidate, descriptor))
    if not matches:
        return None
    if len(matches) != 1:
        providers = ", ".join(candidate.id for candidate, _ in matches)
        raise ProviderError(
            f"Link id {link_id!r} is declared by multiple providers: {providers}"
        )
    return matches[0]


def provider_for_transport(
    transport_id: str,
    *,
    include_legacy: bool = False,
) -> tuple[ProviderCandidate, TransportDescriptor | LinkDescriptor] | None:
    """Resolve a canonical Edge transport, falling back to a 2.x Link id."""

    matches: list[
        tuple[ProviderCandidate, TransportDescriptor | LinkDescriptor]
    ] = []
    for candidate in discover_providers(include_legacy=include_legacy):
        if candidate.manifest is None:
            continue
        descriptors = (
            *candidate.manifest.transports,
            *candidate.manifest.links,
        )
        for descriptor in descriptors:
            if descriptor.id == transport_id:
                matches.append((candidate, descriptor))
    if not matches:
        return None
    provider_ids = {candidate.id for candidate, _ in matches}
    if len(provider_ids) != 1:
        providers = ", ".join(sorted(provider_ids))
        raise ProviderError(
            f"Transport id {transport_id!r} is declared by multiple "
            f"providers: {providers}"
        )
    # A provider may publish the same id in both arrays during the 2.x
    # compatibility window. Prefer the canonical Transport descriptor.
    canonical = [
        item for item in matches if isinstance(item[1], TransportDescriptor)
    ]
    return canonical[0] if canonical else matches[0]


def provider_for_template(
    template_id: str,
    *,
    include_legacy: bool = False,
) -> tuple[ProviderCandidate, TemplateDescriptor] | None:
    matches: list[tuple[ProviderCandidate, TemplateDescriptor]] = []
    for candidate in discover_providers(include_legacy=include_legacy):
        if candidate.manifest is None:
            continue
        for descriptor in candidate.manifest.templates:
            if descriptor.id == template_id:
                matches.append((candidate, descriptor))
    if not matches:
        return None
    if len(matches) != 1:
        providers = ", ".join(candidate.id for candidate, _ in matches)
        raise ProviderError(
            f"Template id {template_id!r} is declared by multiple providers: "
            f"{providers}"
        )
    candidate, descriptor = matches[0]
    if candidate.error:
        raise ProviderError(
            f"Provider {candidate.id!r} was rejected: {candidate.error}"
        )
    return candidate, descriptor


def provider_template_ids() -> tuple[str, ...]:
    result: set[str] = set()
    duplicates: set[str] = set()
    for candidate in discover_providers(include_legacy=False):
        if candidate.error is not None or candidate.manifest is None:
            continue
        for descriptor in candidate.manifest.templates:
            if descriptor.id in result:
                duplicates.add(descriptor.id)
            result.add(descriptor.id)
    return tuple(sorted(result - duplicates))
