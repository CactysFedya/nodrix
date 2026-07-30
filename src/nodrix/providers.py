"""Metadata-first discovery and trusted loading for Provider API 1."""

from __future__ import annotations

import base64
from dataclasses import dataclass, replace
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import stat
import threading
import time
from typing import Any, Iterable, Mapping

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from . import __version__
from .errors import ProviderError
from .provider_api import (
    PROVIDER_ENTRY_POINT_GROUP,
    NodeDescriptor,
    ProbeDescriptor,
    ProviderManifest,
    ProviderMetadata,
    ProviderRuntime,
    negotiate_features,
)


CORE_PROVIDER_FEATURES = frozenset(
    {
        "manifest.v2",
        "python-node-api.2",
        "plugin-c-abi.2",
        "ndrx2",
        "native-runner",
        "provider-api.1",
    }
)
MAX_PROVIDER_METADATA_BYTES = 1024 * 1024
DEFAULT_TRUST_STORE = Path.home() / ".config" / "nodrix" / "trust" / "providers"


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


def _safe_distribution_file(
    distribution: importlib.metadata.Distribution,
    filename: str,
    *,
    required: bool,
) -> Path | None:
    matches = [
        item
        for item in distribution.files or ()
        if Path(str(item)).name == filename
    ]
    if not matches:
        if required:
            raise ValueError(f"distribution has no {filename}")
        return None
    if len(matches) != 1:
        raise ValueError(f"distribution contains multiple {filename} files")
    path = Path(distribution.locate_file(matches[0]))
    if path.is_symlink():
        raise ValueError(f"{filename} must not be a symbolic link")
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise ValueError(f"cannot inspect {filename}: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise ValueError(f"{filename} must be a regular file")
    return path.resolve()


def _distribution_identity(
    distribution: importlib.metadata.Distribution,
) -> tuple[str, str]:
    name = str(
        distribution.metadata.get("Name")
        or getattr(distribution, "name", "")
        or "unknown"
    )
    version = str(distribution.version or "unknown")
    return name, version


def _external_candidates(
    paths: Iterable[str | os.PathLike[str]] | None = None,
) -> list[ProviderCandidate]:
    kwargs: dict[str, Any] = {}
    if paths is not None:
        kwargs["path"] = [os.fspath(path) for path in paths]
    result: list[ProviderCandidate] = []
    for distribution in importlib.metadata.distributions(**kwargs):
        entry_points = [
            item
            for item in distribution.entry_points
            if item.group == PROVIDER_ENTRY_POINT_GROUP
        ]
        if not entry_points:
            continue
        distribution_name, distribution_version = _distribution_identity(
            distribution
        )
        if len(entry_points) != 1:
            for entry_point in entry_points:
                result.append(
                    ProviderCandidate(
                        id=entry_point.name,
                        distribution=distribution_name,
                        distribution_version=distribution_version,
                        manifest=None,
                        document=None,
                        entry_point=entry_point,
                        metadata_path=None,
                        signature_path=None,
                        error=(
                            "a Provider API 1 distribution must declare exactly "
                            "one nodrix.providers entry point"
                        ),
                    )
                )
            continue
        entry_point = entry_points[0]
        metadata_path: Path | None = None
        signature_path: Path | None = None
        try:
            metadata_path = _safe_distribution_file(
                distribution,
                "nodrix-provider.json",
                required=True,
            )
            assert metadata_path is not None
            signature_path = _safe_distribution_file(
                distribution,
                "nodrix-provider.sig",
                required=False,
            )
            document = _read_json(metadata_path)
            if not isinstance(document, dict):
                raise ValueError("provider manifest must be a JSON object")
            manifest = ProviderManifest.from_dict(document)
            if entry_point.name != manifest.metadata.id:
                raise ValueError(
                    "entry-point name must equal provider metadata id"
                )
            if (
                distribution_version != "unknown"
                and distribution_version != manifest.metadata.version
            ):
                raise ValueError(
                    "distribution version does not match provider metadata"
                )
            result.append(
                ProviderCandidate(
                    id=manifest.metadata.id,
                    distribution=distribution_name,
                    distribution_version=distribution_version,
                    manifest=manifest,
                    document=document,
                    entry_point=entry_point,
                    metadata_path=metadata_path,
                    signature_path=signature_path,
                )
            )
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            result.append(
                ProviderCandidate(
                    id=entry_point.name,
                    distribution=distribution_name,
                    distribution_version=distribution_version,
                    manifest=None,
                    document=None,
                    entry_point=entry_point,
                    metadata_path=metadata_path,
                    signature_path=signature_path,
                    error=str(exc),
                )
            )
    return result


def _legacy_manifest(
    provider_id: str,
    name: str,
    *,
    description: str,
    nodes: Iterable[NodeDescriptor] = (),
    probes: Iterable[ProbeDescriptor] = (),
    features: Iterable[str] = (),
) -> ProviderManifest:
    return ProviderManifest(
        metadata=ProviderMetadata(
            id=provider_id,
            name=name,
            version=__version__,
            description=description,
            features=tuple(features),
        ),
        nodes=tuple(nodes),
        probes=tuple(probes),
    )


def _node(
    node_id: str,
    factory: str,
    inputs: Mapping[str, str],
    outputs: Mapping[str, str],
) -> NodeDescriptor:
    return NodeDescriptor(
        id=node_id,
        factory=factory,
        inputs=dict(inputs),
        outputs=dict(outputs),
    )


def _legacy_candidates() -> list[ProviderCandidate]:
    manifests = [
        _legacy_manifest(
            "nodrix.core",
            "Nodrix Core",
            description="Compatibility adapter for Core and base SDK nodes.",
            features=("runtime.core",),
            nodes=(
                _node(
                    "core.synthetic_source",
                    "nodrix.builtin_nodes:SyntheticSource",
                    {},
                    {"output": "core.object"},
                ),
                _node(
                    "core.identity",
                    "nodrix.builtin_nodes:IdentityNode",
                    {"input": "core.any"},
                    {"output": "core.any"},
                ),
                _node(
                    "core.delay",
                    "nodrix.builtin_nodes:DelayNode",
                    {"input": "core.any"},
                    {"output": "core.any"},
                ),
                _node(
                    "core.counter_sink",
                    "nodrix.builtin_nodes:CounterSink",
                    {"input": "core.any"},
                    {},
                ),
                _node(
                    "core.stream_source",
                    "nodrix.builtin_nodes:StreamSource",
                    {},
                    {"output": "core.any"},
                ),
                _node(
                    "sink.console",
                    "nodrix.builtin_nodes:ConsoleSink",
                    {"input": "core.any"},
                    {},
                ),
                _node(
                    "sink.jsonl",
                    "nodrix.builtin_nodes:JsonlSink",
                    {"input": "core.any"},
                    {},
                ),
            ),
            probes=(
                ProbeDescriptor(
                    id="nodrix.core.device",
                    callable="nodrix.device:device_doctor",
                    timeout_seconds=3.0,
                ),
            ),
        ),
        _legacy_manifest(
            "nodrix.vision",
            "Nodrix Vision Legacy Provider",
            description="Compatibility adapter for built-in Vision Node IDs.",
            features=("domain.vision",),
            nodes=(
                _node(
                    "vision.video_source",
                    "nodrix.builtin_nodes:VideoSource",
                    {},
                    {"frame": "vision.frame"},
                ),
                _node(
                    "vision.resize",
                    "nodrix.builtin_nodes:ResizeNode",
                    {"frame": "vision.frame"},
                    {"frame": "vision.frame"},
                ),
                _node(
                    "vision.jpeg_encoder",
                    "nodrix.builtin_nodes:JpegEncoderNode",
                    {"frame": "vision.frame"},
                    {"frame": "vision.encoded_frame"},
                ),
                _node(
                    "vision.jpeg_decoder",
                    "nodrix.builtin_nodes:JpegDecoderNode",
                    {"frame": "vision.encoded_frame"},
                    {"frame": "vision.frame"},
                ),
                _node(
                    "sink.video_writer",
                    "nodrix.builtin_nodes:VideoWriterSink",
                    {"frame": "vision.frame"},
                    {},
                ),
                _node(
                    "vision.letterbox",
                    "nodrix.vision.nodes:LetterboxNode",
                    {"frame": "vision.frame"},
                    {"frame": "vision.frame"},
                ),
                _node(
                    "vision.ncnn_detector",
                    "nodrix.vision.nodes:NcnnDetectorNode",
                    {"frame": "vision.frame"},
                    {"detections": "vision.detections"},
                ),
                _node(
                    "vision.bytetrack",
                    "nodrix.vision.nodes:ByteTrackNode",
                    {"detections": "vision.detections"},
                    {"tracks": "vision.tracks"},
                ),
                _node(
                    "vision.realtime_bytetrack",
                    "nodrix.vision.nodes:RealtimeByteTrackNode",
                    {"detections": "vision.detections"},
                    {"tracks": "vision.tracks"},
                ),
                _node(
                    "vision.overlay",
                    "nodrix.vision.nodes:OverlayNode",
                    {
                        "frame": "vision.frame",
                        "tracks": "vision.tracks",
                    },
                    {"frame": "vision.frame"},
                ),
            ),
            probes=(
                ProbeDescriptor(
                    id="nodrix.vision.dependencies",
                    callable="nodrix.providers:_legacy_vision_probe",
                ),
            ),
        ),
        _legacy_manifest(
            "nodrix.media",
            "Nodrix Media Legacy Provider",
            description="Compatibility adapter for built-in FFmpeg Node IDs.",
            features=("domain.media",),
            nodes=(
                _node(
                    "media.ffmpeg_source",
                    "nodrix.media:FFmpegSource",
                    {},
                    {"frame": "vision.frame"},
                ),
                _node(
                    "media.ffmpeg_writer",
                    "nodrix.media:FFmpegWriter",
                    {"frame": "vision.frame"},
                    {},
                ),
                _node(
                    "media.ffmpeg_encoder",
                    "nodrix.media:FFmpegEncoder",
                    {"frame": "vision.frame"},
                    {"encoded": "vision.encoded_frame"},
                ),
                _node(
                    "media.encoded_writer",
                    "nodrix.media:EncodedWriter",
                    {"frame": "vision.encoded_frame"},
                    {},
                ),
            ),
            probes=(
                ProbeDescriptor(
                    id="nodrix.media.ffmpeg",
                    callable="nodrix.media:media_doctor",
                    timeout_seconds=5.0,
                ),
            ),
        ),
        _legacy_manifest(
            "nodrix.recording",
            "Nodrix Recording Legacy Provider",
            description="Compatibility adapter for NDRX2 source and writer nodes.",
            features=("domain.recording",),
            nodes=(
                _node(
                    "record.ndrx_source",
                    "nodrix.recording:NdrxSourceNode",
                    {},
                    {"output": "core.any"},
                ),
                _node(
                    "record.ndrx_writer",
                    "nodrix.recording:NdrxWriterNode",
                    {"input": "core.any"},
                    {},
                ),
            ),
        ),
        _legacy_manifest(
            "nodrix.ros2",
            "Nodrix ROS 2 Legacy Provider",
            description="Compatibility adapter for generic rclpy source and sink.",
            features=("transport.ros2",),
            nodes=(
                _node(
                    "ros2.source",
                    "nodrix.ros2_adapter:Ros2Source",
                    {},
                    {"output": "core.any"},
                ),
                _node(
                    "ros2.sink",
                    "nodrix.ros2_adapter:Ros2Sink",
                    {"input": "core.any"},
                    {},
                ),
            ),
            probes=(
                ProbeDescriptor(
                    id="nodrix.ros2.rclpy",
                    callable="nodrix.providers:_legacy_ros2_probe",
                ),
            ),
        ),
    ]
    return [
        ProviderCandidate(
            id=manifest.metadata.id,
            distribution="nodrix",
            distribution_version=__version__,
            manifest=manifest,
            document=manifest.to_dict(),
            entry_point=None,
            metadata_path=None,
            signature_path=None,
            internal=True,
        )
        for manifest in manifests
    ]


def _legacy_vision_probe() -> dict[str, Any]:
    return {
        "status": "ok",
        "numpy": importlib.util.find_spec("numpy") is not None,
        "opencv": importlib.util.find_spec("cv2") is not None,
    }


def _legacy_ros2_probe() -> dict[str, Any]:
    available = importlib.util.find_spec("rclpy") is not None
    return {
        "status": "ok" if available else "unavailable",
        "rclpy": available,
        "reason": None if available else "rclpy is not installed",
    }


def discover_providers(
    *,
    include_legacy: bool = True,
    paths: Iterable[str | os.PathLike[str]] | None = None,
) -> list[ProviderCandidate]:
    """Discover provider metadata without importing provider modules."""

    candidates = _external_candidates(paths)
    if include_legacy:
        candidates.extend(_legacy_candidates())
    by_id: dict[str, list[int]] = {}
    for index, candidate in enumerate(candidates):
        by_id.setdefault(candidate.id, []).append(index)
    for provider_id, indexes in by_id.items():
        if len(indexes) <= 1:
            continue
        message = f"duplicate provider id {provider_id!r}"
        for index in indexes:
            previous = candidates[index].error
            candidates[index] = replace(
                candidates[index],
                error=f"{previous}; {message}" if previous else message,
            )
    return sorted(
        candidates,
        key=lambda item: (item.id, item.distribution),
    )


def resolve_provider(
    provider_id: str,
    *,
    include_legacy: bool = True,
    paths: Iterable[str | os.PathLike[str]] | None = None,
) -> ProviderCandidate:
    candidates = discover_providers(
        include_legacy=include_legacy,
        paths=paths,
    )
    exact = [item for item in candidates if item.id == provider_id]
    if not exact and "." not in provider_id:
        exact = [
            item
            for item in candidates
            if item.id.rsplit(".", 1)[-1] == provider_id
        ]
    if not exact:
        raise ProviderError(f"Provider {provider_id!r} is not installed")
    if len(exact) != 1:
        choices = ", ".join(item.id for item in exact)
        raise ProviderError(
            f"Provider alias {provider_id!r} is ambiguous: {choices}"
        )
    return exact[0]


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
        compatible = Version(__version__) in SpecifierSet(
            metadata.requires_nodrix
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
    negotiation = negotiate_features(metadata, CORE_PROVIDER_FEATURES)
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


def provider_record(
    candidate: ProviderCandidate,
    *,
    policy: ProviderPolicy | None = None,
) -> dict[str, Any]:
    verification = verify_candidate(candidate, policy=policy)
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
    return [
        provider_record(candidate, policy=policy)
        for candidate in discover_providers(
            include_legacy=include_legacy,
            paths=paths,
        )
    ]


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
            )
        else:
            try:
                runtime = ProviderRuntime(
                    provider_id=str(produced.provider_id),
                    nodes=dict(produced.nodes),
                    probes=dict(produced.probes),
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
    undeclared_nodes = sorted(set(runtime.nodes) - declared_nodes)
    undeclared_probes = sorted(set(runtime.probes) - declared_probes)
    if undeclared_nodes or undeclared_probes:
        raise ProviderError(
            "Provider runtime attempted to register undeclared ids; "
            f"nodes={undeclared_nodes}, probes={undeclared_probes}"
        )
    return runtime


_LOADED_PROVIDERS: dict[tuple[str, str], LoadedProvider] = {}


def reset_provider_cache() -> None:
    """Clear process-local imports; intended for installers and tests."""

    _LOADED_PROVIDERS.clear()


def load_provider(
    provider_id: str,
    *,
    policy: ProviderPolicy | None = None,
    include_legacy: bool = True,
    paths: Iterable[str | os.PathLike[str]] | None = None,
) -> LoadedProvider:
    candidate = resolve_provider(
        provider_id,
        include_legacy=include_legacy,
        paths=paths,
    )
    verification = verify_candidate(candidate, policy=policy)
    if verification.errors:
        raise ProviderError(
            f"Provider {candidate.id!r} was rejected: "
            + "; ".join(verification.errors)
        )
    key = (candidate.id, verification.metadata_sha256 or "internal")
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
    for candidate in discover_providers(include_legacy=include_legacy):
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


def verify_provider_nodes(
    references: Iterable[str],
    *,
    policy: ProviderPolicy,
) -> list[ProviderVerification]:
    """Verify every external provider referenced by a pipeline before import."""

    selected: dict[str, ProviderCandidate] = {}
    for reference in references:
        resolved = provider_for_node(reference, include_legacy=False)
        if resolved is not None:
            candidate, _descriptor = resolved
            selected[candidate.id] = candidate
    verifications = [
        verify_candidate(candidate, policy=policy)
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
    "provider_for_node",
    "verify_provider_nodes",
    "run_provider_probe",
    "reset_provider_cache",
]
