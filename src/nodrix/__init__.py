"""Nodrix Core public SDK."""

from .buffers import BufferPool
from .cv_types import ManagedBuffer, MemoryType, register_message_type
from .device import DmaBufHandle, DmaBufPlane
from .memory import (
    CudaIpcHandle,
    ExternalMemoryHandle,
    MemoryAccess,
    MemoryPlan,
    MemoryRequirement,
    memory_summary,
    plan_memory,
)
from .messages import Message
from .errors import (
    ManifestError,
    NodrixError,
    PluginError,
    ProviderError,
    RuntimeGraphError,
)
from .manifest import (
    EdgeConfig,
    NodeConfig,
    PipelineManifest,
    QueueConfig,
    load_manifest,
    load_manifest_details,
    load_fragment,
)
from .shared_memory import SharedBufferDescriptor, SharedBufferPool
from .node import Node, NodeContext, SinkNode, SourceNode
from .lifecycle import HealthStatus, LifecycleState
from .wire import register_wire_codec
from .provider_api import (
    PROVIDER_API_VERSION,
    PROVIDER_ENTRY_POINT_GROUP,
    PROVIDER_SCHEMA,
    FeatureNegotiation,
    NodeDescriptor,
    ProbeDescriptor,
    ProviderManifest,
    ProviderMetadata,
    ProviderRuntime,
    TemplateDescriptor,
    negotiate_features,
)

__all__ = [
    "Message",
    "Node",
    "NodeContext",
    "SourceNode",
    "SinkNode",
    "BufferPool",
    "SharedBufferPool",
    "SharedBufferDescriptor",
    "ManagedBuffer",
    "MemoryType",
    "MemoryAccess",
    "MemoryRequirement",
    "MemoryPlan",
    "DmaBufPlane",
    "DmaBufHandle",
    "CudaIpcHandle",
    "ExternalMemoryHandle",
    "plan_memory",
    "memory_summary",
    "register_message_type",
    "register_wire_codec",
    "LifecycleState",
    "HealthStatus",
    "PipelineManifest",
    "NodeConfig",
    "EdgeConfig",
    "QueueConfig",
    "load_manifest",
    "load_manifest_details",
    "load_fragment",
    "NodrixError",
    "ManifestError",
    "PluginError",
    "ProviderError",
    "RuntimeGraphError",
    "PROVIDER_API_VERSION",
    "PROVIDER_ENTRY_POINT_GROUP",
    "PROVIDER_SCHEMA",
    "ProviderMetadata",
    "NodeDescriptor",
    "ProbeDescriptor",
    "TemplateDescriptor",
    "ProviderManifest",
    "ProviderRuntime",
    "FeatureNegotiation",
    "negotiate_features",
]

__version__ = "2.1.0"
