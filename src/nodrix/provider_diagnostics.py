"""Provider conformance verification and bounded diagnostics."""

from __future__ import annotations

import threading
import time
from typing import Any, Iterable, Mapping

from .errors import ProviderError
from .provider_api import ProbeDescriptor
from .provider_common import (
    CORE_PROVIDER_FEATURES,
    LoadedProvider,
    ProviderCandidate,
    ProviderPolicy,
    ProviderVerification,
)
from .provider_discovery import discover_providers
from .provider_loading import (
    _load_symbol,
    load_provider,
    provider_for_application,
    provider_for_link,
    provider_for_node,
    provider_for_resource,
    provider_for_session,
    provider_for_transport,
)
from .provider_verification import _installed_provider_features, verify_candidate

def verify_provider_nodes(
    references: Iterable[str],
    *,
    policy: ProviderPolicy,
    session_references: Iterable[str] = (),
    resource_references: Iterable[str] = (),
    application_references: Iterable[str] = (),
    transport_references: Iterable[str] = (),
    link_references: Iterable[str] = (),
) -> list[ProviderVerification]:
    """Verify every external provider referenced by a pipeline before import."""

    selected: dict[str, ProviderCandidate] = {}
    for reference in references:
        resolved = provider_for_node(reference, include_legacy=False)
        if resolved is not None:
            candidate, _descriptor = resolved
            selected[candidate.id] = candidate
    for reference in session_references:
        resolved_session = provider_for_session(reference, include_legacy=False)
        if resolved_session is not None:
            candidate, _descriptor = resolved_session
            selected[candidate.id] = candidate
    for reference in resource_references:
        resolved_resource = provider_for_resource(
            reference,
            include_legacy=False,
        )
        if resolved_resource is not None:
            candidate, _descriptor = resolved_resource
            selected[candidate.id] = candidate
    for reference in application_references:
        resolved_application = provider_for_application(
            reference,
            include_legacy=False,
        )
        if resolved_application is not None:
            candidate, _descriptor = resolved_application
            selected[candidate.id] = candidate
    for reference in transport_references:
        resolved_transport = provider_for_transport(
            reference,
            include_legacy=False,
        )
        if resolved_transport is not None:
            candidate, _descriptor = resolved_transport
            selected[candidate.id] = candidate
    for reference in link_references:
        resolved_link = provider_for_link(reference, include_legacy=False)
        if resolved_link is not None:
            candidate, _descriptor = resolved_link
            selected[candidate.id] = candidate
    if policy.production:
        # A selected provider may import contracts or services supplied by
        # another provider. Verify every installed provider that advertises a
        # required non-Core capability before any selected entry point imports.
        candidates = discover_providers(include_legacy=False)
        changed = True
        while changed:
            changed = False
            required = {
                feature
                for candidate in selected.values()
                if candidate.metadata is not None
                for feature in candidate.metadata.requires_features
                if feature not in CORE_PROVIDER_FEATURES
            }
            for candidate in candidates:
                if (
                    candidate.id in selected
                    or candidate.error is not None
                    or candidate.metadata is None
                    or not required.intersection(candidate.metadata.features)
                ):
                    continue
                selected[candidate.id] = candidate
                changed = True
    available = _installed_provider_features(
        discover_providers(include_legacy=True)
    )
    verifications = [
        verify_candidate(
            candidate,
            policy=policy,
            available_features=available,
        )
        for candidate in selected.values()
    ]
    failures = [
        item
        for item in verifications
        if item.errors
    ]
    if failures:
        rendered = "; ".join(
            f"{item.provider_id}: {', '.join(item.errors)}"
            for item in failures
        )
        raise ProviderError(
            f"Pipeline provider verification failed: {rendered}"
        )
    return verifications


def _probe_callable(
    loaded: LoadedProvider,
    descriptor: ProbeDescriptor,
) -> Any:
    value = loaded.runtime.probes.get(descriptor.id)
    return value if value is not None else _load_symbol(descriptor.callable)


def run_provider_probe(
    candidate: ProviderCandidate,
    descriptor: ProbeDescriptor,
    *,
    deep: bool,
    policy: ProviderPolicy | None = None,
) -> dict[str, Any]:
    if descriptor.depth == "deep" and not deep:
        return {
            "id": descriptor.id,
            "depth": descriptor.depth,
            "status": "skipped",
            "reason": "deep probe requires --deep",
            "permissions": list(descriptor.permissions),
        }
    started = time.monotonic()
    result: dict[str, Any] = {}
    failure: list[BaseException] = []

    def invoke() -> None:
        try:
            loaded = load_provider(candidate.id, policy=policy)
            callable_value = _probe_callable(loaded, descriptor)
            if not callable(callable_value):
                raise TypeError(
                    f"probe {descriptor.callable!r} is not callable"
                )
            value = callable_value()
            if isinstance(value, Mapping):
                result.update(value)
            elif isinstance(value, bool):
                result.update(
                    {
                        "available": value,
                        "status": "ok" if value else "unavailable",
                    }
                )
            else:
                result.update({"status": "ok", "value": value})
        except BaseException as exc:
            failure.append(exc)

    worker = threading.Thread(
        target=invoke,
        name=f"nodrix-probe-{descriptor.id}",
        daemon=True,
    )
    worker.start()
    worker.join(float(descriptor.timeout_seconds))
    duration_ms = round((time.monotonic() - started) * 1000.0, 3)
    if worker.is_alive():
        return {
            "id": descriptor.id,
            "depth": descriptor.depth,
            "status": "timeout",
            "duration_ms": duration_ms,
            "timeout_seconds": descriptor.timeout_seconds,
            "permissions": list(descriptor.permissions),
        }
    if failure:
        exc = failure[0]
        return {
            "id": descriptor.id,
            "depth": descriptor.depth,
            "status": "error",
            "duration_ms": duration_ms,
            "error": f"{type(exc).__name__}: {exc}",
            "permissions": list(descriptor.permissions),
        }
    status = str(result.get("status", "ok"))
    if status not in {
        "ok",
        "warning",
        "unavailable",
        "degraded",
        "error",
    }:
        status = "warning"
    return {
        "id": descriptor.id,
        "depth": descriptor.depth,
        "status": status,
        "duration_ms": duration_ms,
        "permissions": list(descriptor.permissions),
        "evidence": result,
    }
