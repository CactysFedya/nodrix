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
import shutil
import threading
import time
from typing import Any, Iterable, Mapping

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from . import __version__
from .errors import ProviderError
from .provider_api import (
    PROVIDER_ENTRY_POINT_GROUP,
    LinkDescriptor,
    NodeDescriptor,
    ProbeDescriptor,
    ProviderManifest,
    ProviderMetadata,
    ProviderRuntime,
    SessionDescriptor,
    TemplateDescriptor,
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
        "provider-api.2",
        "provider-sessions.1",
        "external-links.1",
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


def _editable_distribution(
    distribution: importlib.metadata.Distribution,
) -> bool:
    try:
        raw = distribution.read_text("direct_url.json")
    except (OSError, UnicodeDecodeError):
        return False
    if not raw:
        return False
    try:
        document = json.loads(raw)
    except ValueError:
        return False
    return bool(
        isinstance(document, Mapping)
        and isinstance(document.get("dir_info"), Mapping)
        and document["dir_info"].get("editable") is True
    )


def _entry_point_package_directories(entry_point: Any) -> tuple[Path, ...]:
    module_name = str(
        getattr(entry_point, "module", "")
        or str(getattr(entry_point, "value", "")).split(":", 1)[0]
    ).strip()
    package_name = module_name.split(".", 1)[0]
    if not package_name:
        return ()
    try:
        spec = importlib.util.find_spec(package_name)
    except (ImportError, AttributeError, ValueError):
        return ()
    if spec is None:
        return ()
    directories: list[Path] = []
    for item in spec.submodule_search_locations or ():
        directories.append(Path(item).resolve())
    if spec.origin and spec.origin not in {"built-in", "frozen"}:
        directories.append(Path(spec.origin).resolve().parent)
    return tuple(dict.fromkeys(directories))


def _safe_distribution_file(
    distribution: importlib.metadata.Distribution,
    filename: str,
    *,
    required: bool,
    entry_point: Any | None = None,
) -> Path | None:
    paths: list[Path] = [
        Path(distribution.locate_file(item)).resolve()
        for item in distribution.files or ()
        if Path(str(item)).name == filename
    ]
    if entry_point is not None and _editable_distribution(distribution):
        for directory in _entry_point_package_directories(entry_point):
            candidate = (directory / filename).resolve()
            if candidate.is_file():
                paths.append(candidate)

    unique: list[Path] = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    if not unique:
        if required:
            raise ValueError(f"distribution has no {filename}")
        return None

    checked: list[Path] = []
    for path in unique:
        if path.is_symlink():
            raise ValueError(f"{filename} must not be a symbolic link")
        try:
            mode = path.stat().st_mode
        except OSError as exc:
            raise ValueError(f"cannot inspect {filename}: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise ValueError(f"{filename} must be a regular file")
        checked.append(path)

    if len(checked) > 1:
        digests = {
            hashlib.sha256(path.read_bytes()).digest()
            for path in checked
        }
        if len(digests) != 1:
            raise ValueError(
                f"distribution contains conflicting {filename} files"
            )
    return sorted(checked, key=str)[0]


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
                entry_point=entry_point,
            )
            assert metadata_path is not None
            signature_path = _safe_distribution_file(
                distribution,
                "nodrix-provider.sig",
                required=False,
                entry_point=entry_point,
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
    return _deduplicate_external_candidates(result)


def _deduplicate_external_candidates(
    candidates: Iterable[ProviderCandidate],
) -> list[ProviderCandidate]:
    grouped: dict[tuple[str, str, str, str], list[ProviderCandidate]] = {}
    for candidate in candidates:
        entry_point = candidate.entry_point
        key = (
            candidate.distribution.lower().replace("_", "-"),
            candidate.distribution_version,
            str(getattr(entry_point, "name", candidate.id)),
            str(getattr(entry_point, "value", "")),
        )
        grouped.setdefault(key, []).append(candidate)

    result: list[ProviderCandidate] = []
    for values in grouped.values():
        valid = [
            item
            for item in values
            if item.manifest is not None and item.document is not None
        ]
        if not valid:
            result.append(values[0])
            continue
        documents = {
            _canonical_document(item.document)
            for item in valid
            if item.document is not None
        }
        if len(documents) == 1:
            result.append(valid[0])
        else:
            result.extend(valid)
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
                NodeDescriptor(
                    id="vision.ncnn_detector_native",
                    factory=(
                        "nodrix.vision.nodes:"
                        "NativeNcnnDetectorNode"
                    ),
                    inputs={"frame": "vision.frame"},
                    outputs={"detections": "vision.detections"},
                    features=("plugin-c-abi.2", "ncnn.native"),
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
    package_root = Path(__file__).resolve().parent
    plugin_names = (
        "libnodrix_ncnn_detector.so",
        "libnodrix_ncnn_detector.dylib",
        "nodrix_ncnn_detector.dll",
        "nodrix_ncnn_detector.so",
    )
    override = os.environ.get("NODRIX_NCNN_PLUGIN")
    native_path = (
        Path(override).expanduser().resolve()
        if override
        else next(
            (
                package_root / "bin" / name
                for name in plugin_names
                if (package_root / "bin" / name).is_file()
            ),
            None,
        )
    )
    native_available = bool(
        native_path is not None and native_path.is_file()
    )
    return {
        "status": "ok",
        "numpy": importlib.util.find_spec("numpy") is not None,
        "opencv": importlib.util.find_spec("cv2") is not None,
        "native_ncnn": native_available,
        "native_ncnn_path": (
            str(native_path) if native_available else None
        ),
    }


def _legacy_ros2_probe() -> dict[str, Any]:
    available = importlib.util.find_spec("rclpy") is not None
    return {
        "status": "ok" if available else "unavailable",
        "rclpy": available,
        "reason": None if available else "rclpy is not installed",
    }


def _provider_file_fingerprint(
    candidates: Iterable[ProviderCandidate],
) -> tuple[tuple[str, int, int], ...]:
    values: list[tuple[str, int, int]] = []
    for candidate in candidates:
        for path in (candidate.metadata_path, candidate.signature_path):
            if path is None:
                continue
            try:
                info = path.stat()
                values.append((str(path), info.st_mtime_ns, info.st_size))
            except OSError:
                values.append((str(path), -1, -1))
    return tuple(sorted(values))


def discover_providers(
    *,
    include_legacy: bool = True,
    paths: Iterable[str | os.PathLike[str]] | None = None,
) -> list[ProviderCandidate]:
    """Discover provider metadata without importing provider modules."""

    path_key = (
        None
        if paths is None
        else tuple(os.path.abspath(os.fspath(path)) for path in paths)
    )
    now = time.monotonic()
    cache_hit = False
    with _PROVIDER_CACHE_LOCK:
        cached = _DISCOVERY_CACHE.get(path_key)
        if (
            path_key is None
            and cached is not None
            and now - cached[0] <= _DISCOVERY_CACHE_TTL_SECONDS
            and cached[2] == _provider_file_fingerprint(cached[1])
        ):
            external = list(cached[1])
            cache_hit = True
        else:
            external = []
    if not cache_hit:
        external = _external_candidates(path_key)
        if path_key is None:
            with _PROVIDER_CACHE_LOCK:
                selected = tuple(external)
                _DISCOVERY_CACHE[path_key] = (
                    now,
                    selected,
                    _provider_file_fingerprint(selected),
                )
    candidates = list(external)
    if include_legacy:
        external_ids = {candidate.id for candidate in candidates}
        candidates.extend(
            candidate
            for candidate in _legacy_candidates()
            if candidate.id not in external_ids
        )
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
            )
        else:
            try:
                runtime = ProviderRuntime(
                    provider_id=str(produced.provider_id),
                    nodes=dict(produced.nodes),
                    probes=dict(produced.probes),
                    sessions=dict(getattr(produced, "sessions", {})),
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
    undeclared_nodes = sorted(set(runtime.nodes) - declared_nodes)
    undeclared_probes = sorted(set(runtime.probes) - declared_probes)
    undeclared_sessions = sorted(set(runtime.sessions) - declared_sessions)
    if undeclared_nodes or undeclared_probes or undeclared_sessions:
        raise ProviderError(
            "Provider runtime attempted to register undeclared ids; "
            f"nodes={undeclared_nodes}, probes={undeclared_probes}, "
            f"sessions={undeclared_sessions}"
        )
    return runtime


_LOADED_PROVIDERS: dict[tuple[str, str], LoadedProvider] = {}


def reset_provider_cache() -> None:
    """Clear process-local imports; intended for installers and tests."""

    with _PROVIDER_CACHE_LOCK:
        _LOADED_PROVIDERS.clear()
        _DISCOVERY_CACHE.clear()


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


def create_provider_project(
    directory: str | Path,
    template_id: str,
    *,
    force: bool = False,
) -> list[Path]:
    """Copy a provider-owned project template without importing its package."""

    resolved = provider_for_template(template_id, include_legacy=False)
    if resolved is None:
        raise ProviderError(f"Provider template {template_id!r} is not installed")
    candidate, descriptor = resolved
    verification = verify_candidate(candidate)
    if verification.errors:
        raise ProviderError(
            f"Provider {candidate.id!r} was rejected: "
            + "; ".join(verification.errors)
        )
    if candidate.metadata_path is None:
        raise ProviderError(
            f"Provider {candidate.id!r} has no template resource location"
        )
    relative = Path(descriptor.source)
    if relative.is_absolute() or ".." in relative.parts:
        raise ProviderError(
            f"Provider template {template_id!r} has an unsafe source path"
        )
    package_root = candidate.metadata_path.parent.resolve()
    source = (package_root / relative).resolve()
    if package_root != source and package_root not in source.parents:
        raise ProviderError(
            f"Provider template {template_id!r} escapes its package"
        )
    if not source.is_dir() or source.is_symlink():
        raise ProviderError(
            f"Provider template {template_id!r} is not a regular directory"
        )

    target_root = Path(directory).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ProviderError(
                f"Provider template {template_id!r} contains a symbolic link: "
                f"{item.relative_to(source)}"
            )
        relative_item = item.relative_to(source)
        target = target_root / relative_item
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            resolved_target = target.resolve()
            if (
                resolved_target != target_root
                and target_root not in resolved_target.parents
            ):
                raise ProviderError(
                    f"Provider template target escapes through a symbolic link: "
                    f"{target}"
                )
            continue
        if not item.is_file():
            raise ProviderError(
                f"Provider template {template_id!r} contains a non-file entry"
            )
        if target.is_symlink():
            raise ProviderError(
                f"Refusing to write a provider template through a symbolic link: "
                f"{target}"
            )
        if target.exists() and not force:
            raise FileExistsError(
                f"Refusing to overwrite existing template file: {target}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = target.parent.resolve()
        if (
            resolved_parent != target_root
            and target_root not in resolved_parent.parents
        ):
            raise ProviderError(
                f"Provider template target escapes through a symbolic link: "
                f"{target.parent}"
            )
        shutil.copyfile(item, target)
        source_mode = item.stat().st_mode
        target.chmod(0o755 if source_mode & stat.S_IXUSR else 0o644)
        created.append(target)
    return created


def verify_provider_nodes(
    references: Iterable[str],
    *,
    policy: ProviderPolicy,
    session_references: Iterable[str] = (),
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
    "provider_for_node",
    "provider_for_session",
    "provider_for_link",
    "provider_for_template",
    "provider_template_ids",
    "create_provider_project",
    "verify_provider_nodes",
    "run_provider_probe",
    "reset_provider_cache",
]
