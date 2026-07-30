from __future__ import annotations

import os
import warnings
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import yaml

from .errors import ManifestError
from .profiles import get_profile


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


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class QueueConfig(StrictModel):
    capacity: int = Field(default=8, ge=1)
    policy: Literal["block", "latest", "drop_oldest", "drop_newest"] = "block"


class SharedPoolConfig(StrictModel):
    block_size: int = Field(default=8 * 1024 * 1024, ge=4096)
    capacity: int = Field(default=8, ge=1, le=4096)
    threshold: int = Field(default=64 * 1024, ge=0)


MemoryDomain = Literal[
    "auto", "cpu", "pinned_cpu", "shared", "dma_buf", "cuda", "rocm",
    "vulkan", "opencl", "metal", "npu", "external",
]


class RuntimeMemoryConfig(StrictModel):
    shared_pool: SharedPoolConfig = Field(default_factory=SharedPoolConfig)
    process_output_pool: SharedPoolConfig = Field(default_factory=SharedPoolConfig)
    default_domain: MemoryDomain = "auto"
    forbid_implicit_copies: bool = False


class ShutdownConfig(StrictModel):
    mode: Literal["graceful", "immediate"] = "graceful"
    timeout_ms: int = Field(default=10_000, ge=0, le=600_000)


class MetricsConfig(StrictModel):
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


class TracingConfig(StrictModel):
    enabled: bool = False
    exporter: Literal["none", "console", "otlp"] = "none"
    endpoint: str | None = None
    service_name: str = "nodrix"

    @model_validator(mode="after")
    def validate_exporter(self) -> "TracingConfig":
        if self.enabled and self.exporter == "otlp" and not self.endpoint:
            raise ValueError("OTLP tracing requires runtime.tracing.endpoint")
        return self


class LoggingConfig(StrictModel):
    level: Literal["debug", "info", "warning", "error"] = "info"
    structured: bool = True


class RuntimeConfig(StrictModel):
    profile: str | None = None
    mode: Literal["offline", "realtime"] = "offline"
    engine: Literal["auto", "unified", "native"] = "auto"
    type_validation: Literal["off", "first", "always"] = "first"
    telemetry_samples: int = Field(default=4096, ge=64, le=1_000_000)
    memory: RuntimeMemoryConfig = Field(default_factory=RuntimeMemoryConfig)
    shutdown: ShutdownConfig = Field(default_factory=ShutdownConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class SynchronizationConfig(StrictModel):
    policy: Literal["exact_sequence", "approximate_timestamp", "latest_available", "zip"] = "exact_sequence"
    tolerance_ms: float = Field(default=20.0, ge=0.0)
    trigger_port: str | None = None
    optional_inputs: list[str] = Field(default_factory=list)


class StreamAccessConfig(StrictModel):
    mode: Literal["open", "token"] = "open"
    token: str | None = None
    token_env: str | None = None
    allow_ips: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_token(self) -> "StreamAccessConfig":
        if self.mode == "token" and not (self.token or self.token_env):
            raise ValueError("Token-protected stream requires token or token_env")
        return self


class StreamExportConfig(StrictModel):
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


class StreamTlsConfig(StrictModel):
    enabled: bool = False
    certificate: str | None = None
    private_key: str | None = None
    client_ca: str | None = None
    require_client_certificate: bool = False
    minimum_version: Literal["TLSv1.2", "TLSv1.3"] = "TLSv1.2"

    @model_validator(mode="after")
    def validate_tls(self) -> "StreamTlsConfig":
        configured = any(
            (self.certificate, self.private_key, self.client_ca, self.require_client_certificate)
        )
        if configured and not self.enabled:
            raise ValueError("streams.tls must be enabled when TLS credentials are configured")
        if self.enabled and not (self.certificate and self.private_key):
            raise ValueError("Enabled stream TLS requires certificate and private_key")
        if self.require_client_certificate and not self.client_ca:
            raise ValueError("Mutual TLS requires client_ca")
        return self


class StreamsConfig(StrictModel):
    exports: list[StreamExportConfig] = Field(default_factory=list)
    bind_host: str = "127.0.0.1"
    listen_port: int = Field(default=0, ge=0, le=65535)
    max_message_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)
    max_handshake_bytes: int = Field(default=64 * 1024, ge=1024, le=16 * 1024 * 1024)
    handshake_timeout_ms: int = Field(default=5000, ge=100, le=60_000)
    max_handshakes: int = Field(default=32, ge=1, le=4096)
    max_clients: int = Field(default=128, ge=1, le=65_536)
    tls: StreamTlsConfig = Field(default_factory=StreamTlsConfig)


class MetadataConfig(StrictModel):
    name: str = Field(min_length=1)
    description: str | None = None


class ExecutionConfig(StrictModel):
    isolation: Literal["in_process", "process"] = "in_process"
    cpu_affinity: list[int] = Field(default_factory=list)
    device: str = "auto"


class FailureConfig(StrictModel):
    policy: Literal[
        "stop_pipeline",
        "restart",
        "restart_node",
        "skip_message",
        "disable_branch",
        "isolate_branch",
        "fallback_node",
    ] = "stop_pipeline"
    max_restarts: int = Field(default=3, ge=0, le=1000)
    backoff_ms: int = Field(default=250, ge=0, le=600_000)
    fallback_uses: str | None = None

    @model_validator(mode="after")
    def validate_fallback(self) -> "FailureConfig":
        if self.policy == "fallback_node" and not self.fallback_uses:
            raise ValueError("fallback_node requires failure.fallback_uses")
        return self


class HealthConfig(StrictModel):
    timeout_ms: int = Field(default=0, ge=0, le=86_400_000)
    on_timeout: Literal["report", "restart", "stop_pipeline"] = "report"


class ResourceConfig(StrictModel):
    memory_limit_mb: int | None = Field(default=None, ge=16)
    cpu_limit: float | None = Field(default=None, gt=0)
    max_message_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)


class NodeMemoryConfig(StrictModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class NodeConfig(StrictModel):
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
    placement: str | None = None


class EdgeMemoryConfig(StrictModel):
    domain: MemoryDomain = "auto"
    allow_copy: bool = True


class EdgeConfig(StrictModel):
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


class FragmentConfig(StrictModel):
    version: str = "1.0.0"
    description: str | None = None
    documentation: str | None = None
    tests: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    nodes: dict[str, NodeConfig]
    blocks: dict[str, str] = Field(default_factory=dict)
    edges: list[EdgeConfig] = Field(default_factory=list)
    fragments: dict[str, "FragmentConfig"] = Field(default_factory=dict)
    hardware_requirements: list[str] = Field(default_factory=list)


class RecordingConfig(StrictModel):
    enabled: bool = False
    streams: list[str] = Field(default_factory=list)
    directory: str = "recordings"
    checkpoint_records: int = Field(default=1024, ge=1, le=1_000_000)
    durable: bool = True


class SecurityConfig(StrictModel):
    require_signed_plugins: bool = False
    allow_unsigned_local_plugins: bool = True
    native_plugin_allowlist: list[str] = Field(default_factory=list)
    reject_world_writable_plugins: bool = True
    secret_providers: list[str] = Field(default_factory=lambda: ["environment"])


class PlacementConfig(StrictModel):
    default: str = "local"
    nodes: dict[str, str] = Field(default_factory=dict)


class PipelineManifest(StrictModel):
    api_version: Literal["nodrix.dev/v1", "nodrix.dev/v2"] = Field(
        default="nodrix.dev/v1",
        alias="apiVersion",
    )
    kind: Literal["Pipeline"] = "Pipeline"
    metadata: MetadataConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    nodes: dict[str, NodeConfig]
    edges: list[EdgeConfig]
    streams: StreamsConfig = Field(default_factory=StreamsConfig)
    fragments: dict[str, FragmentConfig] = Field(default_factory=dict)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    placement: PlacementConfig = Field(default_factory=PlacementConfig)

    @model_validator(mode="after")
    def validate_node_names(self) -> "PipelineManifest":
        if self.api_version == "nodrix.dev/v2":
            required = {
                "metadata",
                "runtime",
                "nodes",
                "fragments",
                "edges",
                "streams",
                "recording",
                "security",
                "placement",
            }
            missing = sorted(required - self.model_fields_set)
            if missing:
                raise ValueError(
                    "Manifest v2 requires explicit sections: " + ", ".join(missing)
                )
            if self.runtime.engine == "auto":
                raise ValueError(
                    "Manifest v2 requires runtime.engine: unified or native"
                )
            legacy_policies = sorted(
                name
                for name, node in self.nodes.items()
                if node.failure.policy in {"restart", "disable_branch"}
            )
            if legacy_policies:
                raise ValueError(
                    "Manifest v2 requires restart_node/isolate_branch; legacy "
                    "failure policy used by: " + ", ".join(legacy_policies)
                )
        else:
            for name, node in self.nodes.items():
                if node.failure.policy in {"restart", "disable_branch"}:
                    replacement = {
                        "restart": "restart_node",
                        "disable_branch": "isolate_branch",
                    }[node.failure.policy]
                    warnings.warn(
                        f"nodes.{name}.failure.policy={node.failure.policy!r} "
                        f"is deprecated; migrate to {replacement!r}",
                        DeprecationWarning,
                        stacklevel=2,
                    )
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
    "execution", "failure", "health", "resources", "memory", "placement",
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


def load_fragment(path: str | Path, *, name: str | None = None) -> FragmentConfig:
    fragment_path = Path(path).expanduser().resolve()
    normalized = _load_fragment_value(
        name or fragment_path.stem,
        {"uses": str(fragment_path)},
        base_dir=fragment_path.parent,
    )
    try:
        return FragmentConfig.model_validate(_expand_env(normalized))
    except (ValidationError, TypeError, ValueError) as exc:
        raise ManifestError(f"Cannot load fragment {fragment_path}: {exc}") from exc


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
        "fragments": deepcopy(raw.get("fragments") or {}),
        "recording": deepcopy(raw.get("recording") or {}),
        "security": deepcopy(raw.get("security") or {}),
        "placement": deepcopy(raw.get("placement") or {}),
    }
    if canonical["apiVersion"] == "nodrix.dev/v2":
        canonical["runtime"].setdefault("engine", "unified")
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
            source=(
                "block:"
                + (
                    block_file.relative_to(base_dir).as_posix()
                    if block_file.is_relative_to(base_dir)
                    else block_file.as_posix()
                )
            ),
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


def _load_fragment_value(
    name: str,
    value: Any,
    *,
    base_dir: Path,
    stack: tuple[Path, ...] = (),
) -> dict[str, Any]:
    if isinstance(value, (str, Path)):
        reference: dict[str, Any] = {"uses": str(value)}
    elif isinstance(value, dict):
        reference = deepcopy(value)
    else:
        raise ManifestError(f"Fragment {name!r} must be a mapping or YAML path")
    uses = reference.pop("uses", None)
    if uses is not None:
        path = Path(str(uses)).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        path = path.resolve()
        if path in stack:
            chain = " -> ".join(str(item) for item in (*stack, path))
            raise ManifestError(f"Recursive fragment import: {chain}")
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ManifestError(f"Cannot load fragment {name!r} from {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ManifestError(f"Fragment file must contain a mapping: {path}")
        if "fragment" in loaded:
            loaded = loaded["fragment"]
        if not isinstance(loaded, dict):
            raise ManifestError(f"Fragment document is invalid: {path}")
        raw = _deep_merge(loaded, reference)
        fragment_base = path.parent
        next_stack = (*stack, path)
    else:
        raw = reference
        fragment_base = base_dir
        next_stack = stack
    raw_nodes = raw.get("nodes") or {}
    raw_blocks = raw.get("blocks") or {}
    if not isinstance(raw_nodes, dict) or not isinstance(raw_blocks, dict):
        raise ManifestError(f"Fragment {name!r} nodes/blocks must be mappings")
    if not raw_nodes and not raw_blocks:
        raise ManifestError(f"Fragment {name!r} requires nodes or blocks")
    nodes: dict[str, Any] = {}
    for node_name, node_value in raw_nodes.items():
        node, _ = _normalize_node(
            str(node_name),
            node_value,
            source=f"fragment:{name}",
        )
        nodes[str(node_name)] = node
    normalized_blocks: dict[str, str] = {}
    for block_name, block_value in raw_blocks.items():
        block_path = _block_path(
            block_value,
            name=str(block_name),
            base_dir=fragment_base,
        )
        try:
            raw_block = yaml.safe_load(block_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ManifestError(
                f"Cannot read fragment block {block_name!r}: {exc}"
            ) from exc
        node, _ = _normalize_node(
            str(block_name),
            raw_block,
            source=f"fragment-block:{block_path}",
        )
        nodes[str(block_name)] = node
        normalized_blocks[str(block_name)] = str(block_path)
    nested = {
        str(nested_name): _load_fragment_value(
            f"{name}.{nested_name}",
            nested_value,
            base_dir=fragment_base,
            stack=next_stack,
        )
        for nested_name, nested_value in dict(raw.get("fragments") or {}).items()
    }
    parameters = deepcopy(raw.get("parameters") or {})
    def set_fragment_parameter(
        target_nodes: dict[str, Any],
        target_fragments: dict[str, Any],
        parts: list[str],
        parameter_value: Any,
    ) -> bool:
        if len(parts) < 2:
            return False
        if parts[0] in target_fragments:
            child = target_fragments[parts[0]]
            return set_fragment_parameter(
                child["nodes"],
                child.get("fragments") or {},
                parts[1:],
                parameter_value,
            )
        if parts[0] not in target_nodes:
            return False
        cursor = target_nodes[parts[0]].setdefault("parameters", {})
        for part in parts[1:-1]:
            child = cursor.get(part)
            if not isinstance(child, dict):
                child = {}
                cursor[part] = child
            cursor = child
        cursor[parts[-1]] = deepcopy(parameter_value)
        return True

    for dotted, parameter_value in parameters.items():
        set_fragment_parameter(
            nodes,
            nested,
            str(dotted).split("."),
            parameter_value,
        )
    return {
        "version": str(raw.get("version", "1.0.0")),
        "description": raw.get("description"),
        "documentation": raw.get("documentation"),
        "tests": list(raw.get("tests") or []),
        "parameters": parameters,
        "inputs": deepcopy(raw.get("inputs") or {}),
        "outputs": deepcopy(raw.get("outputs") or {}),
        "nodes": nodes,
        "blocks": normalized_blocks,
        "edges": [_parse_flow_item(item) for item in raw.get("flow", raw.get("edges", []))],
        "fragments": nested,
        "hardware_requirements": list(raw.get("hardware_requirements") or []),
    }


def _expand_fragment(
    instance: str,
    fragment: dict[str, Any],
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, str],
    dict[str, str],
]:
    nodes = {
        f"{instance}__{name}": deepcopy(config)
        for name, config in dict(fragment["nodes"]).items()
    }
    nested_inputs: dict[str, dict[str, str]] = {}
    nested_outputs: dict[str, dict[str, str]] = {}
    edges: list[dict[str, Any]] = []
    for nested_name, nested in dict(fragment.get("fragments") or {}).items():
        child_instance = f"{instance}__{nested_name}"
        child_nodes, child_edges, child_inputs, child_outputs = _expand_fragment(
            child_instance,
            nested,
        )
        nodes.update(child_nodes)
        edges.extend(child_edges)
        nested_inputs[nested_name] = child_inputs
        nested_outputs[nested_name] = child_outputs

    def resolve(reference: str, *, source: bool) -> str:
        name, separator, port = str(reference).partition(".")
        if not separator:
            raise ManifestError(
                f"Fragment {instance!r} port reference must use node.port: {reference!r}"
            )
        if name in fragment["nodes"]:
            return f"{instance}__{name}.{port}"
        mappings = nested_outputs if source else nested_inputs
        if name in mappings and port in mappings[name]:
            return mappings[name][port]
        raise ManifestError(
            f"Fragment {instance!r} references unknown {'output' if source else 'input'}: {reference}"
        )

    for edge in fragment.get("edges") or []:
        resolved = deepcopy(edge)
        resolved["from"] = resolve(str(edge["from"]), source=True)
        resolved["to"] = resolve(str(edge["to"]), source=False)
        edges.append(resolved)
    inputs = {
        str(port): resolve(str(reference), source=False)
        for port, reference in dict(fragment.get("inputs") or {}).items()
    }
    outputs = {
        str(port): resolve(str(reference), source=True)
        for port, reference in dict(fragment.get("outputs") or {}).items()
    }
    return nodes, edges, inputs, outputs


def _normalize_and_expand_fragments(
    canonical: dict[str, Any],
    *,
    base_dir: Path,
) -> dict[str, Any]:
    result = deepcopy(canonical)
    raw_fragments = result.get("fragments") or {}
    if not isinstance(raw_fragments, dict):
        raise ManifestError("fragments must be a mapping")
    fragments = {
        str(name): _load_fragment_value(str(name), value, base_dir=base_dir)
        for name, value in raw_fragments.items()
    }
    result["fragments"] = fragments
    fragment_inputs: dict[str, dict[str, str]] = {}
    fragment_outputs: dict[str, dict[str, str]] = {}
    for name, fragment in fragments.items():
        nodes, edges, inputs, outputs = _expand_fragment(name, fragment)
        duplicated = sorted(set(result.get("nodes") or {}) & set(nodes))
        if duplicated:
            raise ManifestError(
                f"Fragment {name!r} expands to duplicate nodes: {', '.join(duplicated)}"
            )
        result.setdefault("nodes", {}).update(nodes)
        result.setdefault("edges", []).extend(edges)
        fragment_inputs[name] = inputs
        fragment_outputs[name] = outputs

    def resolve_outer(reference: str, *, source: bool) -> str:
        name, separator, port = str(reference).partition(".")
        if not separator:
            return reference
        mappings = fragment_outputs if source else fragment_inputs
        if name not in mappings:
            return reference
        if port not in mappings[name]:
            raise ManifestError(
                f"Fragment {name!r} has no public {'output' if source else 'input'} {port!r}"
            )
        return mappings[name][port]

    for edge in result.get("edges") or []:
        edge["from"] = resolve_outer(str(edge["from"]), source=True)
        edge["to"] = resolve_outer(str(edge["to"]), source=False)
    return result


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
        canonical = _normalize_and_expand_fragments(
            canonical,
            base_dir=manifest_path.parent,
        )
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
