"""Unified, side-effect-aware diagnostics for Core and providers."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import sys
from typing import Any, Iterable

from . import __version__
from .device import device_doctor
from .native_runtime import NativeToolchain
from .providers import (
    ProviderCandidate,
    ProviderPolicy,
    discover_providers,
    provider_record,
    run_provider_probe,
)


DOCTOR_SCHEMA = "nodrix-doctor/1"


def _core_native_check() -> dict[str, Any]:
    data = NativeToolchain(Path.cwd()).doctor()
    packaged = Path(str(data["packaged_runner"]))
    available = packaged.is_file() or bool(data["runner_exists"])
    return {
        "id": "core.native",
        "status": "ok" if available else "unavailable",
        "available": available,
        "evidence": data,
    }


def _core_device_check() -> dict[str, Any]:
    try:
        evidence = device_doctor()
    except Exception as exc:
        return {
            "id": "core.device",
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "id": "core.device",
        "status": "ok",
        "evidence": evidence,
    }


def _core_data_plane_check(*, deep: bool) -> dict[str, Any]:
    if not deep:
        return {
            "id": "core.data_plane",
            "status": "ok",
            "mode": "metadata",
            "evidence": {
                "shared_memory_contract": True,
                "process_isolation_contract": True,
                "active_allocation_test": False,
            },
        }
    try:
        from .shared_memory import SharedBufferPool

        with SharedBufferPool(4096, 2) as pool:
            lease = pool.acquire(16)
            lease.memoryview()[:4] = b"NDRX"
            round_trip = bytes(lease.memoryview()[:4]) == b"NDRX"
            lease.release()
            statistics = pool.stats()
        return {
            "id": "core.data_plane",
            "status": "ok" if round_trip else "error",
            "mode": "deep",
            "evidence": {
                "shared_memory_round_trip": round_trip,
                "pool": statistics,
                "active_allocation_test": True,
            },
        }
    except Exception as exc:
        return {
            "id": "core.data_plane",
            "status": "error",
            "mode": "deep",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _select_candidates(
    candidates: list[ProviderCandidate],
    provider_id: str | None,
) -> list[ProviderCandidate]:
    if provider_id is None:
        return candidates
    exact = [item for item in candidates if item.id == provider_id]
    if not exact and "." not in provider_id:
        exact = [
            item
            for item in candidates
            if item.id.rsplit(".", 1)[-1] == provider_id
        ]
    if not exact:
        return [
            ProviderCandidate(
                id=provider_id,
                distribution="",
                distribution_version="",
                manifest=None,
                document=None,
                entry_point=None,
                metadata_path=None,
                signature_path=None,
                error=f"Provider {provider_id!r} is not installed",
            )
        ]
    if len(exact) > 1:
        choices = ", ".join(item.id for item in exact)
        return [
            ProviderCandidate(
                id=provider_id,
                distribution="",
                distribution_version="",
                manifest=None,
                document=None,
                entry_point=None,
                metadata_path=None,
                signature_path=None,
                error=f"Provider alias {provider_id!r} is ambiguous: {choices}",
            )
        ]
    return exact


def _provider_diagnostics(
    candidate: ProviderCandidate,
    *,
    deep: bool,
    policy: ProviderPolicy,
) -> dict[str, Any]:
    record = provider_record(candidate, policy=policy)
    verification = record["verification"]
    probes: list[dict[str, Any]] = []
    if not verification["errors"] and candidate.manifest is not None:
        probes = [
            run_provider_probe(
                candidate,
                descriptor,
                deep=deep,
                policy=policy,
            )
            for descriptor in candidate.manifest.probes
        ]
    record["diagnostics"] = probes
    if verification["errors"]:
        record["status"] = "error"
    elif any(
        item["status"] in {"error", "timeout", "degraded", "warning"}
        for item in probes
    ):
        record["status"] = "degraded"
    elif probes and all(item["status"] == "unavailable" for item in probes):
        record["status"] = "unavailable"
    else:
        record["status"] = "ok"
    return record


def doctor_report(
    *,
    deep: bool = False,
    provider_id: str | None = None,
    production: bool = False,
    trust_store: str | Path | None = None,
    allowlist: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return one deterministic report for all Core and provider diagnostics.

    The default mode performs only safe provider probes.  Device acquisition,
    shared-memory allocation, and any provider-declared deep probes require
    ``deep=True``.
    """

    policy = ProviderPolicy.from_environment(
        production=production,
        trust_store=trust_store,
        allowlist=allowlist,
    )
    candidates = _select_candidates(
        discover_providers(include_legacy=True),
        provider_id,
    )
    core_checks = [
        _core_native_check(),
        _core_device_check(),
        _core_data_plane_check(deep=deep),
    ]
    provider_checks = [
        _provider_diagnostics(
            candidate,
            deep=deep,
            policy=policy,
        )
        for candidate in candidates
    ]
    has_error = any(item["status"] == "error" for item in core_checks) or any(
        item["status"] == "error" for item in provider_checks
    )
    has_degraded = any(
        item["status"] in {"degraded", "warning"}
        for item in core_checks
    ) or any(
        item["status"] in {"degraded", "warning"}
        for item in provider_checks
    )
    return {
        "schema": DOCTOR_SCHEMA,
        "status": "error" if has_error else "degraded" if has_degraded else "ok",
        "mode": "deep" if deep else "safe",
        "production": production,
        "runtime": {
            "plyctl": __version__,
            "nodrix": __version__,
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "executable": sys.executable,
            "process_id": os.getpid(),
        },
        "policy": {
            "trust_store": str(policy.trust_store),
            "allowlist": sorted(policy.allowlist),
        },
        "core": core_checks,
        "providers": provider_checks,
    }


__all__ = ["DOCTOR_SCHEMA", "doctor_report"]
