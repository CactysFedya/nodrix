"""Metadata-first provider discovery and compatibility candidates."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import stat
import time
from typing import Any, Iterable, Mapping

from . import __version__
from .errors import ProviderError
from .provider_api import (
    NodeDescriptor,
    PLYCTL_PROVIDER_ENTRY_POINT_GROUP,
    ProbeDescriptor,
    ProviderManifest,
    ProviderMetadata,
    SUPPORTED_PROVIDER_ENTRY_POINT_GROUPS,
)
from .provider_common import (
    _DISCOVERY_CACHE,
    _DISCOVERY_CACHE_TTL_SECONDS,
    _PROVIDER_CACHE_LOCK,
    _canonical_document,
    _read_json,
    ProviderCandidate,
)


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


def _provider_document_paths(
    distribution: importlib.metadata.Distribution,
    entry_point: Any,
) -> tuple[Path, Path | None]:
    """Resolve canonical or legacy metadata, rejecting ambiguous content."""

    canonical = _safe_distribution_file(
        distribution,
        "plyctl-provider.json",
        required=False,
        entry_point=entry_point,
    )
    legacy = _safe_distribution_file(
        distribution,
        "nodrix-provider.json",
        required=False,
        entry_point=entry_point,
    )
    if canonical is None and legacy is None:
        raise ValueError(
            "distribution has no plyctl-provider.json or nodrix-provider.json"
        )
    if canonical is not None and legacy is not None:
        canonical_document = _read_json(canonical)
        legacy_document = _read_json(legacy)
        if not isinstance(canonical_document, dict) or not isinstance(
            legacy_document, dict
        ):
            raise ValueError("provider manifest must be a JSON object")
        normalized_canonical = dict(canonical_document)
        normalized_legacy = dict(legacy_document)
        for document in (normalized_canonical, normalized_legacy):
            schema = str(document.get("schema", ""))
            if schema.startswith("plyctl-provider/"):
                document["schema"] = schema.replace(
                    "plyctl-provider/", "nodrix-provider/", 1
                )
        if _canonical_document(normalized_canonical) != _canonical_document(
            normalized_legacy
        ):
            raise ValueError(
                "distribution contains conflicting Plyctl and Nodrix provider metadata"
            )
    metadata = canonical or legacy
    assert metadata is not None
    signature_name = (
        "plyctl-provider.sig"
        if canonical is not None
        else "nodrix-provider.sig"
    )
    signature = _safe_distribution_file(
        distribution,
        signature_name,
        required=False,
        entry_point=entry_point,
    )
    return metadata, signature


def _external_candidates(
    paths: Iterable[str | os.PathLike[str]] | None = None,
) -> list[ProviderCandidate]:
    kwargs: dict[str, Any] = {}
    if paths is not None:
        kwargs["path"] = [os.fspath(path) for path in paths]
    result: list[ProviderCandidate] = []
    for distribution in importlib.metadata.distributions(**kwargs):
        discovered_entry_points = [
            item
            for item in distribution.entry_points
            if item.group in SUPPORTED_PROVIDER_ENTRY_POINT_GROUPS
        ]
        if not discovered_entry_points:
            continue
        unique_entry_points: dict[tuple[str, str], Any] = {}
        for item in sorted(
            discovered_entry_points,
            key=lambda value: value.group != PLYCTL_PROVIDER_ENTRY_POINT_GROUP,
        ):
            unique_entry_points.setdefault((item.name, item.value), item)
        entry_points = list(unique_entry_points.values())
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
                            "a provider distribution must declare exactly one "
                            "unique supported provider entry point"
                        ),
                    )
                )
            continue
        entry_point = entry_points[0]
        metadata_path: Path | None = None
        signature_path: Path | None = None
        try:
            metadata_path, signature_path = _provider_document_paths(
                distribution, entry_point
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
            "Plyctl Core",
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
            "Plyctl Vision Legacy Provider",
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
            "Plyctl Media Legacy Provider",
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
            "Plyctl Recording Legacy Provider",
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
            "Plyctl ROS 2 Legacy Provider",
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

    if paths is None:
        configured_paths = os.environ.get("NODRIX_PROVIDER_PATH", "")
        if configured_paths:
            paths = tuple(
                item
                for item in configured_paths.split(os.pathsep)
                if item
            )

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
