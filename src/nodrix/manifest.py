from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import yaml

from .errors import ManifestError
from .profiles import get_profile, profile_names


_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            if name in os.environ:
                return os.environ[name]
            if default is not None:
                return default
            raise ManifestError(f"Environment variable {name!r} is not set")
        return _ENV_RE.sub(repl, value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


class QueueConfig(BaseModel):
    capacity: int = Field(default=8, ge=1)
    policy: Literal["block", "latest", "drop_oldest", "drop_newest"] = "block"


class SharedPoolConfig(BaseModel):
    block_size: int = Field(default=8 * 1024 * 1024, ge=4096)
    capacity: int = Field(default=8, ge=1, le=4096)
    threshold: int = Field(default=64 * 1024, ge=0)


MemoryDomain = Literal[
    "auto", "cpu", "pinned_cpu", "shared", "dma_buf", "cuda", "rocm",
    "vulkan", "opencl", "metal", "npu", "external",
]


class RuntimeMemoryConfig(BaseModel):
    shared_pool: SharedPoolConfig = Field(default_factory=SharedPoolConfig)
    process_output_pool: SharedPoolConfig = Field(default_factory=SharedPoolConfig)
    default_domain: MemoryDomain = "auto"
    forbid_implicit_copies: bool = False


class ShutdownConfig(BaseModel):
    mode: Literal["graceful", "immediate"] = "graceful"
    timeout_ms: int = Field(default=10_000, ge=0, le=600_000)


class MetricsConfig(BaseModel):
    enabled: bool = True
    interval_ms: int = Field(default=1000, ge=100, le=60_000)
    listen: str | None = None

    @model_validator(mode="after")
    def validate_listen(self) -> "MetricsConfig":
        if self.listen is not None:
            host, separator, port = self.listen.rpartition(":")
            if not separator or not host or not port.isdigit() or not 0 <= int(port) <= 65535:
                raise ValueError("runtime.metrics.listen must use host:port")
        return self


class RuntimeConfig(BaseModel):
    profile: str | None = None
    mode: Literal["offline", "realtime"] = "offline"
    engine: Literal["auto", "unified", "native"] = "auto"
    type_validation: Literal["off", "first", "always"] = "first"
    telemetry_samples: int = Field(default=4096, ge=64, le=1_000_000)
    memory: RuntimeMemoryConfig = Field(default_factory=RuntimeMemoryConfig)
    shutdown: ShutdownConfig = Field(default_factory=ShutdownConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


class SynchronizationConfig(BaseModel):
    policy: Literal["exact_sequence", "approximate_timestamp", "latest_available", "zip"] = "exact_sequence"
    tolerance_ms: float = Field(default=20.0, ge=0.0)
    trigger_port: str | None = None


class StreamAccessConfig(BaseModel):
    mode: Literal["open", "token"] = "open"
    token: str | None = None
    token_env: str | None = None
    allow_ips: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_token(self) -> "StreamAccessConfig":
        if self.mode == "token" and not (self.token or self.token_env):
            raise ValueError("Token-protected stream requires token or token_env")
        return self


class StreamExportConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1)
    source: str = Field(alias="from")
    queue: QueueConfig = Field(default_factory=lambda: QueueConfig(capacity=2, policy="latest"))
    access: StreamAccessConfig = Field(default_factory=StreamAccessConfig)

    @model_validator(mode="after")
    def validate_export(self) -> "StreamExportConfig":
        if not self.name.startswith("/"):
            raise ValueError(f"Stream name must start with '/': {self.name!r}")
        if self.source.count(".") < 1:
            raise ValueError(f"Stream source must be in node.port form: {self.source!r}")
        return self


class StreamsConfig(BaseModel):
    exports: list[StreamExportConfig] = Field(default_factory=list)
    bind_host: str = "0.0.0.0"
    listen_port: int = Field(default=0, ge=0, le=65535)
    max_message_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)
    max_handshake_bytes: int = Field(default=64 * 1024, ge=1024, le=16 * 1024 * 1024)


class MetadataConfig(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None


class ExecutionConfig(BaseModel):
    isolation: Literal["in_process", "process"] = "in_process"
    cpu_affinity: list[int] = Field(default_factory=list)
    device: str = "auto"


class FailureConfig(BaseModel):
    policy: Literal["stop_pipeline", "restart", "skip_message", "disable_branch"] = "stop_pipeline"
    max_restarts: int = Field(default=3, ge=0, le=1000)
    backoff_ms: int = Field(default=250, ge=0, le=600_000)


class HealthConfig(BaseModel):
    timeout_ms: int = Field(default=0, ge=0, le=86_400_000)
    on_timeout: Literal["report", "restart", "stop_pipeline"] = "report"


class ResourceConfig(BaseModel):
    memory_limit_mb: int | None = Field(default=None, ge=16)
    cpu_limit: float | None = Field(default=None, gt=0)
    max_message_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)


class NodeMemoryConfig(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class NodeConfig(BaseModel):
    uses: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    synchronization: SynchronizationConfig = Field(default_factory=SynchronizationConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    failure: FailureConfig = Field(default_factory=FailureConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    memory: NodeMemoryConfig = Field(default_factory=NodeMemoryConfig)


class EdgeMemoryConfig(BaseModel):
    domain: MemoryDomain = "auto"
    allow_copy: bool = True


class EdgeConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: str = Field(alias="from")
    target: str = Field(alias="to")
    queue: QueueConfig = Field(default_factory=QueueConfig)
    memory: EdgeMemoryConfig = Field(default_factory=EdgeMemoryConfig)

    @model_validator(mode="after")
    def validate_refs(self) -> "EdgeConfig":
        for field_name, ref in (("from", self.source), ("to", self.target)):
            if ref.count(".") < 1:
                raise ValueError(f"{field_name} must be in node.port form: {ref!r}")
        return self


class PipelineManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_version: str = Field(default="nodrix.dev/v1", alias="apiVersion")
    kind: Literal["Pipeline"] = "Pipeline"
    metadata: MetadataConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    nodes: dict[str, NodeConfig]
    edges: list[EdgeConfig]
    streams: StreamsConfig = Field(default_factory=StreamsConfig)

    @model_validator(mode="after")
    def validate_node_names(self) -> "PipelineManifest":
        if not self.nodes:
            raise ValueError("At least one node is required")
        for name in self.nodes:
            if "." in name:
                raise ValueError(f"Node name cannot contain '.': {name!r}")
        stream_names: set[str] = set()
        for export in self.streams.exports:
            if export.name in stream_names:
                raise ValueError(f"Duplicate stream export name: {export.name!r}")
            stream_names.add(export.name)
        return self


_NODE_RESERVED = {
    "use", "uses", "parameters", "inputs", "outputs", "synchronization",
    "execution", "failure", "health", "resources", "memory",
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def canonical_config_path(dotted: str, node_names: Iterable[str] | None = None) -> str:
    parts = [part for part in dotted.split(".") if part]
    known_nodes = set(node_names or ())
    if len(parts) >= 2 and parts[0] in known_nodes:
        parts.insert(0, "nodes")
    if len(parts) >= 3 and parts[0] == "nodes" and parts[2] not in {
        "uses", "parameters", "inputs", "outputs", "synchronization", "execution",
        "failure", "health", "resources", "memory",
    }:
        parts.insert(2, "parameters")
    return ".".join(parts)


def _set_path(target: dict[str, Any], dotted: str, value: Any) -> None:
    dotted = canonical_config_path(dotted, dict(target.get("nodes") or {}).keys())
    parts = [part for part in dotted.split(".") if part]
    if not parts:
        raise ManifestError("Override path cannot be empty")
    cursor = target
    for part in parts[:-1]:
        next_value = cursor.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            cursor[part] = next_value
        cursor = next_value
    cursor[parts[-1]] = value


def _flatten_paths(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten_paths(item, path))
    elif isinstance(value, list):
        result[prefix] = value
    else:
        result[prefix] = value
    return result


def _parse_flow_item(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        if "->" not in item:
            raise ManifestError(f"Compact flow item must contain '->': {item!r}")
        source, target = (part.strip() for part in item.split("->", 1))
        return {"from": source, "to": target}
    if isinstance(item, dict):
        return deepcopy(item)
    raise ManifestError(f"Unsupported compact flow item: {item!r}")


def _normalize_node(node_name: str, raw_node: Any, *, source: str) -> tuple[dict[str, Any], dict[str, str]]:
    if not isinstance(raw_node, dict):
        raise ManifestError(f"Node {node_name!r} from {source} must be a mapping")
    uses = raw_node.get("use", raw_node.get("uses"))
    if not uses:
        raise ManifestError(f"Node {node_name!r} from {source} requires 'use'")
    node: dict[str, Any] = {"uses": uses}
    direct_parameters = {key: deepcopy(value) for key, value in raw_node.items() if key not in _NODE_RESERVED}
    explicit_parameters = deepcopy(raw_node.get("parameters") or {})
    node["parameters"] = _deep_merge(direct_parameters, explicit_parameters)
    for key in _NODE_RESERVED - {"use", "uses", "parameters"}:
        if key in raw_node:
            node[key] = deepcopy(raw_node[key])
    sources = {
        f"nodes.{node_name}.{path}": source
        for path in _flatten_paths(node)
    }
    return node, sources


def _block_path(value: Any, *, name: str, base_dir: Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise ManifestError(f"Block {name!r} must be a YAML file path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    path = path.resolve()
    if not path.is_file():
        raise ManifestError(f"Block {name!r} does not exist: {path}")
    return path


def load_block(path: str | Path, *, name: str | None = None) -> NodeConfig:
    block_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(block_path.read_text(encoding="utf-8"))
        node, _ = _normalize_node(name or block_path.stem, raw, source=f"block:{block_path}")
        return NodeConfig.model_validate(_expand_env(node))
    except (OSError, yaml.YAMLError, ValidationError, TypeError, ValueError) as exc:
        if isinstance(exc, ManifestError):
            raise
        raise ManifestError(f"Cannot load block {block_path}: {exc}") from exc


def _normalize_compact(
    raw: dict[str, Any], *, base_dir: Path
) -> tuple[dict[str, Any], dict[str, str], dict[str, Path]]:
    compact = "name" in raw or "flow" in raw or "publish" in raw or "blocks" in raw or any(
        isinstance(item, dict) and "use" in item for item in dict(raw.get("nodes") or {}).values()
    )
    sources: dict[str, str] = {}
    block_files: dict[str, Path] = {}
    if not compact:
        canonical = deepcopy(raw)
        for path in _flatten_paths(canonical):
            sources[path] = "pipeline.yaml"
        return canonical, sources, block_files

    name = raw.get("name") or dict(raw.get("metadata") or {}).get("name")
    if not name:
        raise ManifestError("Compact manifest requires 'name'")
    canonical: dict[str, Any] = {
        "apiVersion": raw.get("apiVersion", "nodrix.dev/v1"),
        "kind": raw.get("kind", "Pipeline"),
        "metadata": {"name": name},
        "runtime": deepcopy(raw.get("runtime") or {}),
        "nodes": {},
        "edges": [],
        "streams": deepcopy(raw.get("streams") or {}),
    }
    description = raw.get("description") or dict(raw.get("metadata") or {}).get("description")
    if description:
        canonical["metadata"]["description"] = description
    profile = raw.get("profile")
    if profile:
        canonical["runtime"]["profile"] = profile

    raw_blocks = raw.get("blocks") or {}
    if not isinstance(raw_blocks, dict):
        raise ManifestError("Compact 'blocks' must be a mapping of name: YAML path")
    for block_name, block_ref in raw_blocks.items():
        block_name = str(block_name)
        block_file = _block_path(block_ref, name=block_name, base_dir=base_dir)
        try:
            raw_block = yaml.safe_load(block_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ManifestError(f"Cannot read block {block_name!r} from {block_file}: {exc}") from exc
        node, node_sources = _normalize_node(
            block_name,
            raw_block,
            source=f"block:{block_file.relative_to(base_dir) if block_file.is_relative_to(base_dir) else block_file}",
        )
        canonical["nodes"][block_name] = node
        sources.update(node_sources)
        block_files[block_name] = block_file

    for node_name, raw_node in dict(raw.get("nodes") or {}).items():
        if node_name in canonical["nodes"]:
            raise ManifestError(f"Node/block name is duplicated: {node_name!r}")
        node, node_sources = _normalize_node(str(node_name), raw_node, source="compact pipeline.yaml")
        canonical["nodes"][node_name] = node
        sources.update(node_sources)

    flow = raw.get("flow", raw.get("edges", []))
    canonical["edges"] = [_parse_flow_item(item) for item in flow]

    publish = raw.get("publish")
    if publish is not None:
        exports = list(canonical["streams"].get("exports") or [])
        if not isinstance(publish, dict):
            raise ManifestError("Compact 'publish' must be a mapping")
        for stream_name, value in publish.items():
            if isinstance(value, str):
                export = {"name": stream_name, "from": value}
            elif isinstance(value, dict):
                export = {"name": stream_name, **deepcopy(value)}
                if "source" in export and "from" not in export:
                    export["from"] = export.pop("source")
                access = export.get("access")
                if isinstance(access, str):
                    export["access"] = {"mode": access}
                    if access == "token":
                        export["access"]["token_env"] = "NODRIX_STREAM_TOKEN"
            else:
                raise ManifestError(f"Publish entry {stream_name!r} must be a string or mapping")
            exports.append(export)
        canonical["streams"]["exports"] = exports

    for path in _flatten_paths(canonical):
        sources.setdefault(path, "compact pipeline.yaml")
    return canonical, sources, block_files


def _apply_block_overrides(raw: dict[str, Any], overrides: list[str] | None) -> dict[str, Any]:
    if not overrides:
        return raw
    result = deepcopy(raw)
    blocks = result.get("blocks")
    if not isinstance(blocks, dict):
        raise ManifestError("--block requires a compact manifest with a 'blocks' mapping")
    for expression in overrides:
        if "=" not in expression:
            raise ManifestError(f"Block override must use name=path syntax: {expression!r}")
        name, path = (part.strip() for part in expression.split("=", 1))
        if not name or not path:
            raise ManifestError(f"Block override must use name=path syntax: {expression!r}")
        if name not in blocks:
            available = ", ".join(sorted(str(item) for item in blocks)) or "none"
            raise ManifestError(f"Unknown block {name!r}; available blocks: {available}")
        blocks[name] = path
    return result


def _apply_profile(
    canonical: dict[str, Any], sources: dict[str, str], profile_override: str | None
) -> tuple[dict[str, Any], dict[str, str]]:
    runtime = dict(canonical.get("runtime") or {})
    profile_name = profile_override or runtime.get("profile")
    if not profile_name:
        return canonical, sources
    try:
        profile = get_profile(str(profile_name))
    except ValueError as exc:
        raise ManifestError(str(exc)) from exc

    result = deepcopy(canonical)
    profile_runtime = deepcopy(profile.get("runtime") or {})
    profile_runtime["profile"] = profile_name
    result["runtime"] = _deep_merge(profile_runtime, runtime)

    node_defaults = dict(profile.get("node_defaults") or {})
    for node_name, node in dict(result.get("nodes") or {}).items():
        defaults = deepcopy(node_defaults.get(str(node.get("uses"))) or {})
        if defaults:
            result["nodes"][node_name] = _deep_merge(defaults, node)

    edge_defaults = deepcopy(profile.get("edge_defaults") or {})
    result["edges"] = [_deep_merge(edge_defaults, edge) for edge in list(result.get("edges") or [])]

    stream_defaults = deepcopy(profile.get("stream_defaults") or {})
    export_queue = stream_defaults.pop("queue", None)
    result["streams"] = _deep_merge(stream_defaults, dict(result.get("streams") or {}))
    if export_queue is not None:
        result["streams"]["exports"] = [
            _deep_merge({"queue": export_queue}, export)
            for export in list(result["streams"].get("exports") or [])
        ]

    for path in _flatten_paths(result):
        if path not in sources:
            sources[path] = f"profile:{profile_name}"
    return result, sources


@dataclass(slots=True)
class ManifestLoadResult:
    manifest: PipelineManifest
    canonical: dict[str, Any]
    sources: dict[str, str]
    path: Path
    block_files: dict[str, Path]


def load_manifest_details(
    path: str | Path,
    *,
    profile: str | None = None,
    overrides: list[str] | None = None,
    block_overrides: list[str] | None = None,
    expand_env: bool = True,
) -> ManifestLoadResult:
    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.exists():
        raise ManifestError(f"Pipeline file does not exist: {manifest_path}")
    try:
        loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ManifestError("Pipeline document must be a mapping")
        loaded = _apply_block_overrides(loaded, block_overrides)
        canonical, sources, block_files = _normalize_compact(loaded, base_dir=manifest_path.parent)
        canonical, sources = _apply_profile(canonical, sources, profile)
        for expression in overrides or []:
            if "=" not in expression:
                raise ManifestError(f"Override must use path=value syntax: {expression!r}")
            dotted, raw_value = expression.split("=", 1)
            parsed_value = yaml.safe_load(raw_value)
            canonical_path = canonical_config_path(dotted.strip(), dict(canonical.get("nodes") or {}).keys())
            _set_path(canonical, canonical_path, parsed_value)
            sources[canonical_path] = "CLI --set"
        expanded = _expand_env(canonical) if expand_env else canonical
        manifest = PipelineManifest.model_validate(expanded)
        resolved = manifest.model_dump(by_alias=True, exclude_none=True)
    except (OSError, yaml.YAMLError, ValidationError, TypeError, ValueError) as exc:
        if isinstance(exc, ManifestError):
            raise
        raise ManifestError(f"Cannot load {manifest_path}: {exc}") from exc
    return ManifestLoadResult(manifest, resolved, sources, manifest_path, block_files)


def load_manifest(
    path: str | Path,
    *,
    profile: str | None = None,
    overrides: list[str] | None = None,
    block_overrides: list[str] | None = None,
) -> PipelineManifest:
    return load_manifest_details(
        path,
        profile=profile,
        overrides=overrides,
        block_overrides=block_overrides,
    ).manifest


def dump_manifest(manifest: PipelineManifest, path: str | Path) -> None:
    data = manifest.model_dump(by_alias=True, exclude_none=True)
    Path(path).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


_SECRET_KEYS = {"token", "password", "secret", "api_key", "apikey", "authorization"}

def _redact(value: Any, key: str = "") -> Any:
    if key.lower() in _SECRET_KEYS and value not in (None, ""):
        if isinstance(value, str) and _ENV_RE.fullmatch(value):
            return value
        return "***REDACTED***"
    if isinstance(value, dict):
        return {item_key: _redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def dump_manifest_redacted(manifest: PipelineManifest, path: str | Path) -> None:
    data = manifest.model_dump(by_alias=True, exclude_none=True)
    Path(path).write_text(yaml.safe_dump(_redact(data), sort_keys=False), encoding="utf-8")


def dump_source_manifest_redacted(source: str | Path, destination: str | Path) -> None:
    source_path = Path(source)
    try:
        raw = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"Cannot read {source_path}: {exc}") from exc
    Path(destination).write_text(yaml.safe_dump(_redact(raw), sort_keys=False), encoding="utf-8")
