from __future__ import annotations

import os
import warnings
import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class UsesConfig(StrictModel):
    """Common provider reference with a 2.x compatibility alias."""

    uses: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def normalize_use_alias(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        alias = normalized.pop("use", None)
        canonical = normalized.get("uses")
        if alias is not None and canonical is not None and alias != canonical:
            raise ValueError("use and uses cannot contain different values")
        if canonical is None and alias is not None:
            normalized["uses"] = alias
        return normalized


class SessionConfig(UsesConfig):
    """One provider-owned resource shared by multiple pipeline Nodes."""

    parameters: dict[str, Any] = Field(default_factory=dict)


class ProviderResourceConfig(UsesConfig):
    """One provider-owned resource shared by Nodes and Applications."""

    parameters: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, str] = Field(default_factory=dict)


class ApplicationConfig(UsesConfig):
    """An external application supervised outside the local data plane."""

    parameters: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, str] = Field(default_factory=dict)


class NodeConfig(UsesConfig):
    parameters: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    synchronization: SynchronizationConfig = Field(default_factory=SynchronizationConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    failure: FailureConfig = Field(default_factory=FailureConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    memory: NodeMemoryConfig = Field(default_factory=NodeMemoryConfig)
    bindings: dict[str, str] = Field(default_factory=dict)
    placement: str | None = None


class EdgeMemoryConfig(StrictModel):
    domain: MemoryDomain = "auto"
    allow_copy: bool = True


class TransportConfig(UsesConfig):
    """Physical or external transport used by one logical Edge."""

    parameters: dict[str, Any] = Field(default_factory=dict)


class EdgeConfig(StrictModel):
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    queue: QueueConfig = Field(default_factory=QueueConfig)
    memory: EdgeMemoryConfig = Field(default_factory=EdgeMemoryConfig)
    transport: TransportConfig | None = None

    @model_validator(mode="after")
    def validate_refs(self) -> "EdgeConfig":
        for field_name, ref in (("from", self.source), ("to", self.target)):
            if ref.count(".") < 1:
                raise ValueError(f"{field_name} must be in node.port form: {ref!r}")
        return self


class ExternalLinkConfig(UsesConfig):
    """A control-plane link compiled by an optional integration provider.

    Unlike ``edges``, external links do not create a Nodrix queue or move a
    payload through the Nodrix runtime.  A provider can use them to describe
    DDS topics, broker routes, service bindings, or equivalent external data
    paths while keeping the ordinary node.port notation.
    """

    source: str = Field(alias="from")
    target: str = Field(alias="to")
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_refs(self) -> "ExternalLinkConfig":
        for field_name, ref in (("from", self.source), ("to", self.target)):
            if ref.count(".") < 1:
                raise ValueError(
                    f"external link {field_name} must use node.port: {ref!r}"
                )
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
    queue_capacity: int = Field(default=256, ge=1, le=1_000_000)


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
    sessions: dict[str, SessionConfig] = Field(default_factory=dict)
    resources: dict[str, ProviderResourceConfig] = Field(default_factory=dict)
    applications: dict[str, ApplicationConfig] = Field(default_factory=dict)
    nodes: dict[str, NodeConfig]
    edges: list[EdgeConfig]
    links: list[ExternalLinkConfig] = Field(
        default_factory=list,
        json_schema_extra={"deprecated": True},
    )
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
        if not self.nodes and not self.applications:
            raise ValueError("At least one node or application is required")
        if (self.sessions or self.resources or self.applications) and self.runtime.engine == "native":
            raise ValueError(
                "Pipeline integrations require runtime.engine: unified"
            )
        resource_names = set(self.sessions) | set(self.resources)
        duplicated_resources = sorted(set(self.sessions) & set(self.resources))
        if duplicated_resources:
            raise ValueError(
                "Session/resource names must be unique: "
                + ", ".join(duplicated_resources)
            )
        for name in resource_names:
            if not name or not name.strip() or "." in name:
                raise ValueError(
                    f"Resource name must be non-empty and cannot contain '.': {name!r}"
                )
        for resource_name, resource in self.resources.items():
            if any(not name.strip() for name in resource.bindings):
                raise ValueError(
                    f"Resource {resource_name!r} contains an empty binding name"
                )
            unknown = sorted(
                set(resource.bindings.values()) - set(self.sessions)
            )
            if unknown:
                raise ValueError(
                    f"Resource {resource_name!r} references unknown sessions: "
                    + ", ".join(unknown)
                )
        endpoint_names = set(self.nodes) | set(self.applications)
        duplicated_endpoints = sorted(set(self.nodes) & set(self.applications))
        if duplicated_endpoints:
            raise ValueError(
                "Node/application names must be unique: "
                + ", ".join(duplicated_endpoints)
            )
        for name in endpoint_names:
            if not name or not name.strip() or "." in name:
                raise ValueError(
                    f"Node/application name must be non-empty and cannot contain '.': {name!r}"
                )
        for node_name, node in self.nodes.items():
            if any(not name.strip() for name in node.bindings):
                raise ValueError(
                    f"Node {node_name!r} contains an empty binding name"
                )
            unknown = sorted(set(node.bindings.values()) - resource_names)
            if unknown:
                raise ValueError(
                    f"Node {node_name!r} references unknown resources: "
                    + ", ".join(unknown)
                )
            if node.bindings and node.execution.isolation != "in_process":
                raise ValueError(
                    f"Node {node_name!r} uses resource bindings and must run "
                    "in_process"
                )
        for application_name, application in self.applications.items():
            if any(not name.strip() for name in application.bindings):
                raise ValueError(
                    f"Application {application_name!r} contains an empty "
                    "binding name"
                )
            unknown = sorted(
                set(application.bindings.values()) - resource_names
            )
            if unknown:
                raise ValueError(
                    f"Application {application_name!r} references unknown "
                    "resources: " + ", ".join(unknown)
                )
        for link in self.links:
            source_name = link.source.split(".", 1)[0]
            target_name = link.target.split(".", 1)[0]
            unknown_nodes = sorted(
                {source_name, target_name} - endpoint_names
            )
            if unknown_nodes:
                raise ValueError(
                    "External link references unknown nodes/applications: "
                    + ", ".join(unknown_nodes)
                )
        for edge in self.edges:
            source_name = edge.source.split(".", 1)[0]
            target_name = edge.target.split(".", 1)[0]
            allowed = endpoint_names if edge.transport is not None else set(self.nodes)
            unknown = sorted({source_name, target_name} - allowed)
            if unknown:
                kind = "transport edge" if edge.transport is not None else "local edge"
                raise ValueError(
                    f"{kind} references unknown endpoints: "
                    + ", ".join(unknown)
                )
        stream_names: set[str] = set()
        for export in self.streams.exports:
            if export.name in stream_names:
                raise ValueError(f"Duplicate stream export name: {export.name!r}")
            stream_names.add(export.name)
        return self
