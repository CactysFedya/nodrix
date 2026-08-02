"""Metadata-first discovery and trusted loading for Provider API 1."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
from typing import Any, Iterable, Mapping

from .errors import ProviderError
from .provider_api import (
    ProviderManifest,
    ProviderMetadata,
    ProviderRuntime,
)


CORE_PROVIDER_FEATURES = frozenset(
    {
        "manifest.v2",
        "python-node-api.2",
        "plugin-c-abi.2",
        "ndrx2",
        "native-runner",
        "provider-api.1",
        "provider-api.2",
        "provider-sessions.1",
        "external-links.1",
        "edge-transports.1",
        "managed-applications.1",
        "managed-resources.1",
        "provider-templates.1",
    }
)
MAX_PROVIDER_METADATA_BYTES = 1024 * 1024
DEFAULT_TRUST_STORE = Path.home() / ".config" / "nodrix" / "trust" / "providers"
_PROVIDER_CACHE_LOCK = threading.RLock()
_DISCOVERY_CACHE_TTL_SECONDS = 1.0
_DISCOVERY_CACHE: dict[
    tuple[str, ...] | None,
    tuple[
        float,
        tuple["ProviderCandidate", ...],
        tuple[tuple[str, int, int], ...],
    ],
] = {}


@dataclass(frozen=True, slots=True)
class ProviderCandidate:
    id: str
    distribution: str
    distribution_version: str
    manifest: ProviderManifest | None
    document: dict[str, Any] | None
    entry_point: Any | None
    metadata_path: Path | None
    signature_path: Path | None
    internal: bool = False
    error: str | None = None

    @property
    def metadata(self) -> ProviderMetadata | None:
        return self.manifest.metadata if self.manifest is not None else None


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    production: bool = False
    trust_store: Path = DEFAULT_TRUST_STORE
    allowlist: frozenset[str] = frozenset()

    @classmethod
    def from_environment(
        cls,
        *,
        production: bool = False,
        trust_store: str | Path | None = None,
        allowlist: Iterable[str] | None = None,
    ) -> ProviderPolicy:
        selected_store = Path(
            trust_store
            or os.environ.get("NODRIX_PROVIDER_TRUST_STORE")
            or DEFAULT_TRUST_STORE
        ).expanduser()
        selected_allowlist = (
            frozenset(str(item).strip() for item in allowlist if str(item).strip())
            if allowlist is not None
            else _environment_allowlist(selected_store)
        )
        return cls(
            production=bool(production),
            trust_store=selected_store,
            allowlist=selected_allowlist,
        )


@dataclass(frozen=True, slots=True)
class ProviderVerification:
    provider_id: str
    status: str
    compatible: bool
    signed: bool
    trusted: bool
    allowlisted: bool
    key_sha256: str | None
    metadata_sha256: str | None
    missing_features: tuple[str, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "status": self.status,
            "compatible": self.compatible,
            "signed": self.signed,
            "trusted": self.trusted,
            "allowlisted": self.allowlisted,
            "key_sha256": self.key_sha256,
            "metadata_sha256": self.metadata_sha256,
            "missing_features": list(self.missing_features),
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class LoadedProvider:
    candidate: ProviderCandidate
    runtime: ProviderRuntime
    verification: ProviderVerification


def _environment_allowlist(trust_store: Path) -> frozenset[str]:
    configured = os.environ.get("NODRIX_PROVIDER_ALLOWLIST")
    if configured is not None:
        return frozenset(
            item.strip()
            for item in configured.split(",")
            if item.strip()
        )
    path = trust_store / "allowlist.json"
    if not path.is_file():
        return frozenset()
    try:
        value = _read_json(path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ProviderError(f"Invalid provider allowlist {path}: {exc}") from exc
    if isinstance(value, dict):
        value = value.get("providers")
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip()
        for item in value
    ):
        raise ProviderError(
            f"Provider allowlist {path} must be a string array or "
            "{'providers': [...]}"
        )
    return frozenset(item.strip() for item in value)


def _pairs_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> Any:
    data = path.read_bytes()
    if len(data) > MAX_PROVIDER_METADATA_BYTES:
        raise ValueError(
            f"metadata exceeds {MAX_PROVIDER_METADATA_BYTES} bytes"
        )
    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_pairs_without_duplicates,
    )


def _canonical_document(document: Mapping[str, Any]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
