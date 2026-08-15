"""Compatibility facade for the typing-first SDK.

The implementation now lives under :mod:`nodrix.sdk`:

    Python callable/class -> decorator -> neutral Definition -> legacy adapter

Existing 2.4 imports from ``nodrix.simplified_sdk`` remain valid while the
runtime and Provider API 2 continue to act as compatibility targets.
"""

from __future__ import annotations

from .sdk import (
    CallableDefinition,
    ComponentSpec,
    Context,
    DependencyDefinition,
    DependencySpec,
    Input,
    MessageDefinition,
    NodeDefinition,
    Outputs,
    Param,
    ParameterDefinition,
    ParameterSpec,
    PortDefinition,
    PortSpec,
    Resource,
    ResourceDefinition,
    message,
    node,
    resource,
)
from .sdk.namespace import PACKAGE_NAMESPACE_OVERRIDE as _PACKAGE_NAMESPACE_OVERRIDE

__all__ = [
    "CallableDefinition",
    "ComponentSpec",
    "Context",
    "DependencyDefinition",
    "DependencySpec",
    "Input",
    "MessageDefinition",
    "NodeDefinition",
    "Outputs",
    "_PACKAGE_NAMESPACE_OVERRIDE",
    "Param",
    "ParameterDefinition",
    "ParameterSpec",
    "PortDefinition",
    "PortSpec",
    "Resource",
    "ResourceDefinition",
    "message",
    "node",
    "resource",
]
