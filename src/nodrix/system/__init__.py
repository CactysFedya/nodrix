"""Nodrix 2.5 canonical backend-neutral System Model."""

from .catalog import DefinitionCatalog
from .compatibility import (
    CompatibilityResult,
    CompatibilityWarning,
    pipeline_manifest_to_system,
)
from .graph import (
    Connection,
    Graph,
    SystemLink,
    split_local_endpoint,
    split_system_endpoint,
)
from .instances import (
    ApplicationInstance,
    Artifact,
    NodeInstance,
    ResourceInstance,
    Target,
)
from .model import SYSTEM_MODEL_API_VERSION, SystemModel
from .validation import (
    SystemDiagnostic,
    SystemValidationError,
    SystemValidationReport,
    validate_system,
)

__all__ = [
    "ApplicationInstance",
    "Artifact",
    "CompatibilityResult",
    "CompatibilityWarning",
    "Connection",
    "DefinitionCatalog",
    "Graph",
    "NodeInstance",
    "ResourceInstance",
    "SYSTEM_MODEL_API_VERSION",
    "SystemDiagnostic",
    "SystemLink",
    "SystemModel",
    "SystemValidationError",
    "SystemValidationReport",
    "Target",
    "pipeline_manifest_to_system",
    "split_local_endpoint",
    "split_system_endpoint",
    "validate_system",
]
