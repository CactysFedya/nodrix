"""Stable public contracts for Plyctl Provider APIs 1 and 2.

Provider metadata is deliberately made of plain, immutable dataclasses.  A
provider distribution can therefore describe itself without importing its
Python package, while the same descriptors remain convenient to construct in
provider code and tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable, Mapping


PROVIDER_API_VERSION = "1"
PROVIDER_SCHEMA = "nodrix-provider/1"
PROVIDER_API_VERSION_V2 = "2"
PROVIDER_SCHEMA_V2 = "nodrix-provider/2"
PLYCTL_PROVIDER_SCHEMA = "plyctl-provider/1"
PLYCTL_PROVIDER_SCHEMA_V2 = "plyctl-provider/2"
SUPPORTED_PROVIDER_API_VERSIONS = frozenset(
    {PROVIDER_API_VERSION, PROVIDER_API_VERSION_V2}
)
SUPPORTED_PROVIDER_SCHEMAS = frozenset(
    {
        PROVIDER_SCHEMA,
        PROVIDER_SCHEMA_V2,
        PLYCTL_PROVIDER_SCHEMA,
        PLYCTL_PROVIDER_SCHEMA_V2,
    }
)
PROVIDER_ENTRY_POINT_GROUP = "nodrix.providers"
PLYCTL_PROVIDER_ENTRY_POINT_GROUP = "plyctl.providers"
SUPPORTED_PROVIDER_ENTRY_POINT_GROUPS = frozenset(
    {PROVIDER_ENTRY_POINT_GROUP, PLYCTL_PROVIDER_ENTRY_POINT_GROUP}
)

_IDENTIFIER = re.compile(r"^[a-z0-9](?:[a-z0-9_.-]*[a-z0-9])?$")
_REFERENCE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$")


def _identifier(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 128 or _IDENTIFIER.fullmatch(text) is None:
        raise ValueError(f"{field_name} must be a lowercase dotted identifier")
    return text


def _reference(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if len(text) > 512 or _REFERENCE.fullmatch(text) is None:
        raise ValueError(f"{field_name} must use module:attribute syntax")
    return text


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be an array")
    result = tuple(str(item).strip() for item in value)
    if any(not item or len(item) > 128 for item in result):
        raise ValueError(f"{field_name} contains an invalid value")
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} must not contain duplicates")
    return result


def _ports(value: object, field_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    result = {str(name): str(kind) for name, kind in value.items()}
    if any(not name or not kind for name, kind in result.items()):
        raise ValueError(f"{field_name} contains an empty port or type")
    return result


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Compatibility and feature contract available before provider import."""

    id: str
    name: str
    version: str
    provider_api: str = PROVIDER_API_VERSION
    requires_nodrix: str = ">=2.1,<3"
    description: str = ""
    features: tuple[str, ...] = ()
    requires_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "provider id"))
        if not self.name.strip() or len(self.name) > 160:
            raise ValueError("provider name is required")
        if not self.version.strip() or len(self.version) > 64:
            raise ValueError("provider version is required")
        if self.provider_api not in SUPPORTED_PROVIDER_API_VERSIONS:
            raise ValueError(
                f"provider API {self.provider_api!r} is unsupported; "
                "expected one of "
                + ", ".join(sorted(SUPPORTED_PROVIDER_API_VERSIONS))
            )
        object.__setattr__(
            self,
            "features",
            _string_tuple(self.features, "features"),
        )
        object.__setattr__(
            self,
            "requires_features",
            _string_tuple(self.requires_features, "requires_features"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProviderMetadata:
        return cls(
            id=value.get("id", ""),
            name=str(value.get("name", "")),
            version=str(value.get("version", "")),
            provider_api=str(value.get("provider_api", "")),
            requires_nodrix=str(value.get("requires_nodrix", ">=2.1,<3")),
            description=str(value.get("description", "")),
            features=_string_tuple(value.get("features"), "features"),
            requires_features=_string_tuple(
                value.get("requires_features"),
                "requires_features",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "provider_api": self.provider_api,
            "requires_nodrix": self.requires_nodrix,
            "description": self.description,
            "features": list(self.features),
            "requires_features": list(self.requires_features),
        }


@dataclass(frozen=True, slots=True)
class NodeDescriptor:
    """One lazily importable Node implementation supplied by a provider."""

    id: str
    factory: str
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    optional_inputs: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    bindings: dict[str, str] = field(default_factory=dict)
    external_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    external_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "node id"))
        object.__setattr__(self, "factory", _reference(self.factory, "node factory"))
        object.__setattr__(self, "inputs", _ports(self.inputs, "node inputs"))
        object.__setattr__(self, "outputs", _ports(self.outputs, "node outputs"))
        optional = _string_tuple(self.optional_inputs, "optional_inputs")
        if not set(optional).issubset(self.inputs):
            raise ValueError("optional_inputs must name declared input ports")
        object.__setattr__(self, "optional_inputs", optional)
        object.__setattr__(
            self,
            "features",
            _string_tuple(self.features, "node features"),
        )
        object.__setattr__(self, "parameters_schema", dict(self.parameters_schema))
        object.__setattr__(
            self,
            "bindings",
            {str(name): str(kind) for name, kind in self.bindings.items()},
        )
        for field_name in ("external_inputs", "external_outputs"):
            value = getattr(self, field_name)
            normalized = {
                str(name): dict(spec)
                for name, spec in value.items()
            }
            if any(not name for name in normalized):
                raise ValueError(f"{field_name} contains an empty port")
            object.__setattr__(self, field_name, normalized)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NodeDescriptor:
        return cls(
            id=value.get("id", ""),
            factory=value.get("factory", ""),
            inputs=_ports(value.get("inputs"), "node inputs"),
            outputs=_ports(value.get("outputs"), "node outputs"),
            optional_inputs=_string_tuple(
                value.get("optional_inputs"),
                "optional_inputs",
            ),
            features=_string_tuple(value.get("features"), "node features"),
            parameters_schema=dict(value.get("parameters_schema") or {}),
            bindings={
                str(name): str(kind)
                for name, kind in dict(value.get("bindings") or {}).items()
            },
            external_inputs={
                str(name): dict(spec)
                for name, spec in dict(value.get("external_inputs") or {}).items()
            },
            external_outputs={
                str(name): dict(spec)
                for name, spec in dict(value.get("external_outputs") or {}).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "factory": self.factory,
            "inputs": dict(self.inputs),
            "outputs": dict(self.outputs),
            "optional_inputs": list(self.optional_inputs),
            "features": list(self.features),
            "parameters_schema": dict(self.parameters_schema),
            "bindings": dict(self.bindings),
            "external_inputs": {
                name: dict(spec) for name, spec in self.external_inputs.items()
            },
            "external_outputs": {
                name: dict(spec) for name, spec in self.external_outputs.items()
            },
        }


@dataclass(frozen=True, slots=True)
class SessionDescriptor:
    """One lazily importable, pipeline-scoped provider session."""

    id: str
    factory: str
    features: tuple[str, ...] = ()
    parameters_schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "session id"))
        object.__setattr__(
            self, "factory", _reference(self.factory, "session factory")
        )
        object.__setattr__(
            self,
            "features",
            _string_tuple(self.features, "session features"),
        )
        object.__setattr__(self, "parameters_schema", dict(self.parameters_schema))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SessionDescriptor":
        return cls(
            id=value.get("id", ""),
            factory=value.get("factory", ""),
            features=_string_tuple(value.get("features"), "session features"),
            parameters_schema=dict(value.get("parameters_schema") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "factory": self.factory,
            "features": list(self.features),
            "parameters_schema": dict(self.parameters_schema),
        }


@dataclass(frozen=True, slots=True)
class ResourceDescriptor:
    """One lazily importable pipeline-scoped managed resource.

    ``SessionDescriptor`` remains supported throughout Plyctl 2.x.  New
    providers should prefer this transport-neutral name when the object is not
    specifically a connection/session.
    """

    id: str
    factory: str
    features: tuple[str, ...] = ()
    parameters_schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "resource id"))
        object.__setattr__(
            self,
            "factory",
            _reference(self.factory, "resource factory"),
        )
        object.__setattr__(
            self,
            "features",
            _string_tuple(self.features, "resource features"),
        )
        object.__setattr__(self, "parameters_schema", dict(self.parameters_schema))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResourceDescriptor":
        return cls(
            id=value.get("id", ""),
            factory=value.get("factory", ""),
            features=_string_tuple(value.get("features"), "resource features"),
            parameters_schema=dict(value.get("parameters_schema") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "factory": self.factory,
            "features": list(self.features),
            "parameters_schema": dict(self.parameters_schema),
        }


@dataclass(frozen=True, slots=True)
class ApplicationDescriptor:
    """One externally managed application supplied by a provider."""

    id: str
    factory: str
    features: tuple[str, ...] = ()
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    bindings: dict[str, str] = field(default_factory=dict)
    external_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    external_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "application id"))
        object.__setattr__(
            self,
            "factory",
            _reference(self.factory, "application factory"),
        )
        object.__setattr__(
            self,
            "features",
            _string_tuple(self.features, "application features"),
        )
        object.__setattr__(self, "parameters_schema", dict(self.parameters_schema))
        object.__setattr__(
            self,
            "bindings",
            {str(name): str(kind) for name, kind in self.bindings.items()},
        )
        for field_name in ("external_inputs", "external_outputs"):
            value = getattr(self, field_name)
            normalized = {str(name): dict(spec) for name, spec in value.items()}
            if any(not name for name in normalized):
                raise ValueError(f"{field_name} contains an empty port")
            object.__setattr__(self, field_name, normalized)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApplicationDescriptor":
        return cls(
            id=value.get("id", ""),
            factory=value.get("factory", ""),
            features=_string_tuple(
                value.get("features"),
                "application features",
            ),
            parameters_schema=dict(value.get("parameters_schema") or {}),
            bindings={
                str(name): str(kind)
                for name, kind in dict(value.get("bindings") or {}).items()
            },
            external_inputs={
                str(name): dict(spec)
                for name, spec in dict(value.get("external_inputs") or {}).items()
            },
            external_outputs={
                str(name): dict(spec)
                for name, spec in dict(value.get("external_outputs") or {}).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "factory": self.factory,
            "features": list(self.features),
            "parameters_schema": dict(self.parameters_schema),
            "bindings": dict(self.bindings),
            "external_inputs": {
                name: dict(spec) for name, spec in self.external_inputs.items()
            },
            "external_outputs": {
                name: dict(spec) for name, spec in self.external_outputs.items()
            },
        }


@dataclass(frozen=True, slots=True)
class LinkDescriptor:
    """A provider-owned external link kind compiled outside the data plane."""

    id: str
    features: tuple[str, ...] = ()
    parameters_schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "link id"))
        object.__setattr__(
            self,
            "features",
            _string_tuple(self.features, "link features"),
        )
        object.__setattr__(self, "parameters_schema", dict(self.parameters_schema))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LinkDescriptor":
        return cls(
            id=value.get("id", ""),
            features=_string_tuple(value.get("features"), "link features"),
            parameters_schema=dict(value.get("parameters_schema") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "features": list(self.features),
            "parameters_schema": dict(self.parameters_schema),
        }


@dataclass(frozen=True, slots=True)
class TransportDescriptor(LinkDescriptor):
    """Transport backend attached to a logical pipeline Edge."""


@dataclass(frozen=True, slots=True)
class ProbeDescriptor:
    """A bounded provider diagnostic.

    ``safe`` probes may run during ordinary ``plyctl doctor``.  ``deep`` probes
    require an explicit ``--deep`` request and declare any expected permission
    or device access in ``permissions``.
    """

    id: str
    callable: str
    depth: str = "safe"
    timeout_seconds: float = 2.0
    permissions: tuple[str, ...] = ()
    cooldown_seconds: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "probe id"))
        object.__setattr__(
            self,
            "callable",
            _reference(self.callable, "probe callable"),
        )
        if self.depth not in {"safe", "deep"}:
            raise ValueError("probe depth must be 'safe' or 'deep'")
        if not 0.05 <= float(self.timeout_seconds) <= 300.0:
            raise ValueError("probe timeout_seconds must be between 0.05 and 300")
        if not 0.0 <= float(self.cooldown_seconds) <= 86400.0:
            raise ValueError("probe cooldown_seconds must be between 0 and 86400")
        object.__setattr__(
            self,
            "permissions",
            _string_tuple(self.permissions, "probe permissions"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProbeDescriptor:
        return cls(
            id=value.get("id", ""),
            callable=value.get("callable", ""),
            depth=str(value.get("depth", "safe")),
            timeout_seconds=float(value.get("timeout_seconds", 2.0)),
            permissions=_string_tuple(
                value.get("permissions"),
                "probe permissions",
            ),
            cooldown_seconds=float(value.get("cooldown_seconds", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "callable": self.callable,
            "depth": self.depth,
            "timeout_seconds": self.timeout_seconds,
            "permissions": list(self.permissions),
            "cooldown_seconds": self.cooldown_seconds,
        }


@dataclass(frozen=True, slots=True)
class TemplateDescriptor:
    """A provider-owned project or pipeline template."""

    id: str
    source: str
    description: str = ""
    features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "template id"))
        if not self.source.strip() or len(self.source) > 512:
            raise ValueError("template source is required")
        object.__setattr__(
            self,
            "features",
            _string_tuple(self.features, "template features"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TemplateDescriptor:
        return cls(
            id=value.get("id", ""),
            source=str(value.get("source", "")),
            description=str(value.get("description", "")),
            features=_string_tuple(
                value.get("features"),
                "template features",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "description": self.description,
            "features": list(self.features),
        }


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    """Validated content of a Plyctl or legacy Nodrix provider document."""

    metadata: ProviderMetadata
    nodes: tuple[NodeDescriptor, ...] = ()
    probes: tuple[ProbeDescriptor, ...] = ()
    templates: tuple[TemplateDescriptor, ...] = ()
    sessions: tuple[SessionDescriptor, ...] = ()
    resources: tuple[ResourceDescriptor, ...] = ()
    applications: tuple[ApplicationDescriptor, ...] = ()
    transports: tuple[TransportDescriptor, ...] = ()
    links: tuple[LinkDescriptor, ...] = ()
    schema: str = PROVIDER_SCHEMA

    def __post_init__(self) -> None:
        if self.schema not in SUPPORTED_PROVIDER_SCHEMAS:
            raise ValueError(
                f"provider schema {self.schema!r} is unsupported; "
                "expected one of "
                + ", ".join(sorted(SUPPORTED_PROVIDER_SCHEMAS))
            )
        if self.schema in {PROVIDER_SCHEMA, PLYCTL_PROVIDER_SCHEMA} and (
            self.sessions
            or self.resources
            or self.applications
            or self.transports
            or self.links
        ):
            raise ValueError(
                "provider sessions, resources, applications, and external "
                "links require a Provider API 2 schema"
            )
        expected_api = (
            PROVIDER_API_VERSION_V2
            if self.schema in {PROVIDER_SCHEMA_V2, PLYCTL_PROVIDER_SCHEMA_V2}
            else PROVIDER_API_VERSION
        )
        if self.metadata.provider_api != expected_api:
            raise ValueError(
                f"provider schema {self.schema!r} requires provider_api "
                f"{expected_api!r}"
            )
        for field_name, values in (
            ("nodes", self.nodes),
            ("probes", self.probes),
            ("templates", self.templates),
            ("sessions", self.sessions),
            ("resources", self.resources),
            ("applications", self.applications),
            ("transports", self.transports),
            ("links", self.links),
        ):
            ids = [item.id for item in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"provider {field_name} must have unique ids")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProviderManifest:
        if not isinstance(value, Mapping):
            raise ValueError("provider manifest must be an object")
        metadata_value = value.get("metadata")
        if not isinstance(metadata_value, Mapping):
            raise ValueError("provider metadata must be an object")

        def array(name: str) -> list[Mapping[str, Any]]:
            raw = value.get(name, [])
            if not isinstance(raw, list) or any(
                not isinstance(item, Mapping) for item in raw
            ):
                raise ValueError(f"provider {name} must be an array of objects")
            return raw

        return cls(
            schema=str(value.get("schema", "")),
            metadata=ProviderMetadata.from_dict(metadata_value),
            nodes=tuple(NodeDescriptor.from_dict(item) for item in array("nodes")),
            probes=tuple(ProbeDescriptor.from_dict(item) for item in array("probes")),
            templates=tuple(
                TemplateDescriptor.from_dict(item)
                for item in array("templates")
            ),
            sessions=tuple(
                SessionDescriptor.from_dict(item)
                for item in array("sessions")
            ),
            resources=tuple(
                ResourceDescriptor.from_dict(item)
                for item in array("resources")
            ),
            applications=tuple(
                ApplicationDescriptor.from_dict(item)
                for item in array("applications")
            ),
            transports=tuple(
                TransportDescriptor.from_dict(item)
                for item in array("transports")
            ),
            links=tuple(
                LinkDescriptor.from_dict(item)
                for item in array("links")
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "metadata": self.metadata.to_dict(),
            "nodes": [item.to_dict() for item in self.nodes],
            "probes": [item.to_dict() for item in self.probes],
            "templates": [item.to_dict() for item in self.templates],
            "sessions": [item.to_dict() for item in self.sessions],
            "resources": [item.to_dict() for item in self.resources],
            "applications": [item.to_dict() for item in self.applications],
            "transports": [item.to_dict() for item in self.transports],
            "links": [item.to_dict() for item in self.links],
        }


@dataclass(frozen=True, slots=True)
class FeatureNegotiation:
    compatible: bool
    available: tuple[str, ...]
    required: tuple[str, ...]
    missing: tuple[str, ...]


@dataclass(slots=True)
class ProviderRuntime:
    """Optional runtime object returned by a provider entry point.

    A provider can rely entirely on the import references in its manifest, or
    return concrete Node classes and probe callables here.  Runtime overrides
    are accepted only for ids already declared in signed metadata.
    """

    provider_id: str
    nodes: Mapping[str, type[Any]] = field(default_factory=dict)
    probes: Mapping[str, Callable[[], Any]] = field(default_factory=dict)
    sessions: Mapping[str, type[Any]] = field(default_factory=dict)
    resources: Mapping[str, type[Any]] = field(default_factory=dict)
    applications: Mapping[str, type[Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.provider_id = _identifier(self.provider_id, "provider runtime id")
        self.nodes = dict(self.nodes)
        self.probes = dict(self.probes)
        self.sessions = dict(self.sessions)
        self.resources = dict(self.resources)
        self.applications = dict(self.applications)


def negotiate_features(
    metadata: ProviderMetadata,
    available: set[str] | frozenset[str] | tuple[str, ...],
) -> FeatureNegotiation:
    known = frozenset(available)
    missing = tuple(
        feature
        for feature in metadata.requires_features
        if feature not in known
    )
    return FeatureNegotiation(
        compatible=not missing,
        available=tuple(sorted(known)),
        required=metadata.requires_features,
        missing=missing,
    )


__all__ = [
    "PROVIDER_API_VERSION",
    "PROVIDER_SCHEMA",
    "PROVIDER_API_VERSION_V2",
    "PROVIDER_SCHEMA_V2",
    "PROVIDER_ENTRY_POINT_GROUP",
    "PLYCTL_PROVIDER_SCHEMA",
    "PLYCTL_PROVIDER_SCHEMA_V2",
    "PLYCTL_PROVIDER_ENTRY_POINT_GROUP",
    "SUPPORTED_PROVIDER_ENTRY_POINT_GROUPS",
    "ProviderMetadata",
    "NodeDescriptor",
    "ProbeDescriptor",
    "TemplateDescriptor",
    "SessionDescriptor",
    "ResourceDescriptor",
    "ApplicationDescriptor",
    "LinkDescriptor",
    "TransportDescriptor",
    "ProviderManifest",
    "ProviderRuntime",
    "FeatureNegotiation",
    "negotiate_features",
]
