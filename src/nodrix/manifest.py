from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import yaml

from .errors import ManifestError


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


class RuntimeConfig(BaseModel):
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


def load_manifest(path: str | Path) -> PipelineManifest:
    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.exists():
        raise ManifestError(f"Pipeline file does not exist: {manifest_path}")
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        raw = _expand_env(raw)
        manifest = PipelineManifest.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError, TypeError) as exc:
        raise ManifestError(f"Cannot load {manifest_path}: {exc}") from exc
    return manifest


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
