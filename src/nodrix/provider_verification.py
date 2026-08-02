"""Provider metadata signing, verification, and inspection records."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from . import __version__
from .errors import ProviderError
from .provider_api import ProviderManifest, negotiate_features
from .provider_common import (
    CORE_PROVIDER_FEATURES,
    _canonical_document,
    _read_json,
    ProviderCandidate,
    ProviderPolicy,
    ProviderVerification,
)

from .provider_discovery import discover_providers, resolve_provider

def sign_provider_metadata(
    metadata_path: str | Path,
    private_key_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    """Create a detached Ed25519 ``nodrix-provider.sig`` document."""

    source = Path(metadata_path).expanduser().resolve()
    document = _read_json(source)
    if not isinstance(document, dict):
        raise ProviderError("Provider metadata must be a JSON object")
    ProviderManifest.from_dict(document)
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ModuleNotFoundError as exc:
        raise ProviderError(
            "Provider signing requires `pip install nodrix[security]`"
        ) from exc
    private_key = serialization.load_pem_private_key(
        Path(private_key_path).expanduser().resolve().read_bytes(),
        password=None,
    )
    if not isinstance(private_key, ed25519.Ed25519PrivateKey):
        raise ProviderError("Provider signing key must be Ed25519")
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signature = {
        "algorithm": "ed25519",
        "key_sha256": hashlib.sha256(public_der).hexdigest(),
        "value": base64.b64encode(
            private_key.sign(_canonical_document(document))
        ).decode("ascii"),
    }
    target = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else source.with_name("nodrix-provider.sig")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(signature, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return target

def _trust_keys(path: Path, *, production: bool) -> dict[str, Any]:
    if not path.exists():
        return {}
    if not path.is_dir():
        raise ProviderError(f"Provider trust store is not a directory: {path}")
    if production and os.name != "nt" and path.stat().st_mode & 0o022:
        raise ProviderError(
            f"Provider trust store must not be group/world-writable: {path}"
        )
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ModuleNotFoundError as exc:
        raise ProviderError(
            "Provider signature verification requires "
            "`pip install nodrix[security]`"
        ) from exc
    keys: dict[str, Any] = {}
    for key_path in sorted(path.glob("*.pem")):
        if key_path.is_symlink() or not key_path.is_file():
            raise ProviderError(
                f"Trusted provider key must be a regular file: {key_path}"
            )
        if production and os.name != "nt" and key_path.stat().st_mode & 0o022:
            raise ProviderError(
                f"Trusted provider key must not be group/world-writable: "
                f"{key_path}"
            )
        key = serialization.load_pem_public_key(key_path.read_bytes())
        if not isinstance(key, ed25519.Ed25519PublicKey):
            raise ProviderError(
                f"Trusted provider key is not Ed25519: {key_path}"
            )
        public_der = key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        fingerprint = hashlib.sha256(public_der).hexdigest()
        if fingerprint in keys:
            raise ProviderError(
                f"Duplicate provider trust key fingerprint: {fingerprint}"
            )
        keys[fingerprint] = key
    return keys


def verify_candidate(
    candidate: ProviderCandidate,
    *,
    policy: ProviderPolicy | None = None,
    available_features: Iterable[str] | None = None,
) -> ProviderVerification:
    selected_policy = policy or ProviderPolicy.from_environment()
    errors: list[str] = []
    if candidate.error:
        errors.append(candidate.error)
    if candidate.manifest is None or candidate.document is None:
        return ProviderVerification(
            provider_id=candidate.id,
            status="invalid",
            compatible=False,
            signed=candidate.signature_path is not None,
            trusted=False,
            allowlisted=False,
            key_sha256=None,
            metadata_sha256=None,
            missing_features=(),
            errors=tuple(errors or ("provider metadata is unavailable",)),
        )
    metadata = candidate.manifest.metadata
    document_bytes = _canonical_document(candidate.document)
    metadata_sha256 = hashlib.sha256(document_bytes).hexdigest()
    compatible = True
    try:
        compatible = SpecifierSet(metadata.requires_nodrix).contains(
            Version(__version__),
            prereleases=True,
        )
    except (InvalidSpecifier, InvalidVersion) as exc:
        compatible = False
        errors.append(f"invalid Nodrix compatibility constraint: {exc}")
    if not compatible and not any(
        item.startswith("invalid Nodrix compatibility") for item in errors
    ):
        errors.append(
            f"provider requires Nodrix {metadata.requires_nodrix}, "
            f"runtime is {__version__}"
        )
    negotiation = negotiate_features(
        metadata,
        _installed_provider_features()
        if available_features is None
        else frozenset(available_features),
    )
    if negotiation.missing:
        errors.append(
            "provider requires unavailable features: "
            + ", ".join(negotiation.missing)
        )
    signed = candidate.signature_path is not None
    trusted = candidate.internal
    key_sha256: str | None = None
    if signed and not candidate.internal:
        try:
            signature_value = _read_json(candidate.signature_path)
            if not isinstance(signature_value, dict):
                raise ValueError("detached signature must be a JSON object")
            if signature_value.get("algorithm") != "ed25519":
                raise ValueError("unsupported provider signature algorithm")
            key_sha256 = str(signature_value.get("key_sha256", ""))
            if len(key_sha256) != 64:
                raise ValueError("invalid provider signing-key fingerprint")
            keys = _trust_keys(
                selected_policy.trust_store,
                production=selected_policy.production,
            )
            key = keys.get(key_sha256)
            if key is None:
                raise ValueError(
                    f"provider signing key is not trusted: {key_sha256}"
                )
            key.verify(
                base64.b64decode(
                    str(signature_value.get("value", "")),
                    validate=True,
                ),
                document_bytes,
            )
            trusted = True
        except Exception as exc:
            errors.append(f"provider signature verification failed: {exc}")
    allowlisted = candidate.internal or candidate.id in selected_policy.allowlist
    if selected_policy.production and not candidate.internal:
        if not signed:
            errors.append("production provider must have a detached signature")
        if not trusted:
            errors.append("production provider must use a trusted signing key")
        if not allowlisted:
            errors.append("provider is not in the production allowlist")
    status = (
        "invalid"
        if errors
        else "internal"
        if candidate.internal
        else "verified"
        if trusted
        else "unsigned"
    )
    return ProviderVerification(
        provider_id=candidate.id,
        status=status,
        compatible=compatible and negotiation.compatible,
        signed=signed,
        trusted=trusted,
        allowlisted=allowlisted,
        key_sha256=key_sha256,
        metadata_sha256=metadata_sha256,
        missing_features=negotiation.missing,
        errors=tuple(errors),
    )


def verify_provider(
    provider_id: str,
    *,
    policy: ProviderPolicy | None = None,
    include_legacy: bool = True,
    paths: Iterable[str | os.PathLike[str]] | None = None,
) -> ProviderVerification:
    return verify_candidate(
        resolve_provider(
            provider_id,
            include_legacy=include_legacy,
            paths=paths,
        ),
        policy=policy,
    )


def _installed_provider_features(
    candidates: Iterable[ProviderCandidate] | None = None,
) -> frozenset[str]:
    """Return Core capabilities plus capabilities advertised by installed providers.

    This keeps feature negotiation metadata-first: optional packages can depend
    on another provider capability without importing either distribution.
    Broken or duplicate candidates never contribute capabilities.
    """

    available = set(CORE_PROVIDER_FEATURES)
    selected = (
        discover_providers(include_legacy=True)
        if candidates is None
        else tuple(candidates)
    )
    for item in selected:
        if item.error is not None or item.metadata is None:
            continue
        try:
            compatible = SpecifierSet(item.metadata.requires_nodrix).contains(
                Version(__version__),
                prereleases=True,
            )
        except (InvalidSpecifier, InvalidVersion):
            compatible = False
        if compatible:
            available.update(item.metadata.features)
    return frozenset(available)


def provider_record(
    candidate: ProviderCandidate,
    *,
    policy: ProviderPolicy | None = None,
    available_features: Iterable[str] | None = None,
) -> dict[str, Any]:
    verification = verify_candidate(
        candidate,
        policy=policy,
        available_features=available_features,
    )
    metadata = candidate.metadata
    return {
        "id": candidate.id,
        "name": None if metadata is None else metadata.name,
        "version": (
            candidate.distribution_version
            if metadata is None
            else metadata.version
        ),
        "distribution": candidate.distribution,
        "source": "legacy" if candidate.internal else "distribution",
        "provider_api": (
            None if metadata is None else metadata.provider_api
        ),
        "requires_nodrix": (
            None if metadata is None else metadata.requires_nodrix
        ),
        "features": [] if metadata is None else list(metadata.features),
        "nodes": (
            [] if candidate.manifest is None
            else [item.to_dict() for item in candidate.manifest.nodes]
        ),
        "probes": (
            [] if candidate.manifest is None
            else [item.to_dict() for item in candidate.manifest.probes]
        ),
        "templates": (
            [] if candidate.manifest is None
            else [item.to_dict() for item in candidate.manifest.templates]
        ),
        "sessions": (
            [] if candidate.manifest is None
            else [item.to_dict() for item in candidate.manifest.sessions]
        ),
        "resources": (
            [] if candidate.manifest is None
            else [item.to_dict() for item in candidate.manifest.resources]
        ),
        "applications": (
            [] if candidate.manifest is None
            else [item.to_dict() for item in candidate.manifest.applications]
        ),
        "transports": (
            [] if candidate.manifest is None
            else [item.to_dict() for item in candidate.manifest.transports]
        ),
        "links": (
            [] if candidate.manifest is None
            else [item.to_dict() for item in candidate.manifest.links]
        ),
        "metadata_path": (
            None
            if candidate.metadata_path is None
            else str(candidate.metadata_path)
        ),
        "signature_path": (
            None
            if candidate.signature_path is None
            else str(candidate.signature_path)
        ),
        "verification": verification.to_dict(),
    }


def provider_records(
    *,
    policy: ProviderPolicy | None = None,
    include_legacy: bool = True,
    paths: Iterable[str | os.PathLike[str]] | None = None,
) -> list[dict[str, Any]]:
    candidates = discover_providers(
        include_legacy=include_legacy,
        paths=paths,
    )
    available = _installed_provider_features(candidates)
    return [
        provider_record(
            candidate,
            policy=policy,
            available_features=available,
        )
        for candidate in candidates
    ]
