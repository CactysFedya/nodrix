"""Loss-aware compatibility lowering from 2.x PipelineManifest to SystemModel."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Literal, Mapping

from ..errors import NodrixError
from ..manifest import PipelineManifest
from .graph import Connection, Graph, SystemLink
from .instances import ApplicationInstance, ResourceInstance, Target
from .model import SystemModel


CompatibilityDisposition = Literal[
    "preserved",
    "transformed",
    "deferred",
    "unsupported",
]


class CompatibilityError(NodrixError):
    """A stored legacy compatibility snapshot cannot be trusted or restored."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "COMPAT400",
    ) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class CompatibilityEntry:
    """One explicit semantic decision made during Pipeline -> System lowering."""

    path: str
    disposition: CompatibilityDisposition
    target: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "disposition": self.disposition,
            "target": self.target,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompatibilityEntry":
        disposition = str(value["disposition"])
        if disposition not in {
            "preserved",
            "transformed",
            "deferred",
            "unsupported",
        }:
            raise CompatibilityError(
                f"unknown compatibility disposition {disposition!r}",
                code="COMPAT404",
            )
        return cls(
            path=str(value["path"]),
            disposition=disposition,  # type: ignore[arg-type]
            target=str(value["target"]),
            message=str(value["message"]),
        )


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    """Machine-readable migration report.

    ``deferred`` means the information is retained losslessly but is not yet a
    canonical SystemModel field because execution/operations semantics belong
    to later architecture layers. Only ``unsupported`` is considered loss.
    """

    source_api_version: str
    source_sha256: str
    entries: tuple[CompatibilityEntry, ...] = ()

    def by_disposition(
        self,
        disposition: CompatibilityDisposition,
    ) -> tuple[CompatibilityEntry, ...]:
        return tuple(
            entry for entry in self.entries
            if entry.disposition == disposition
        )

    @property
    def preserved(self) -> tuple[CompatibilityEntry, ...]:
        return self.by_disposition("preserved")

    @property
    def transformed(self) -> tuple[CompatibilityEntry, ...]:
        return self.by_disposition("transformed")

    @property
    def deferred(self) -> tuple[CompatibilityEntry, ...]:
        return self.by_disposition("deferred")

    @property
    def unsupported(self) -> tuple[CompatibilityEntry, ...]:
        return self.by_disposition("unsupported")

    @property
    def lossless(self) -> bool:
        return bool(self.source_sha256) and not self.unsupported

    @property
    def reversible(self) -> bool:
        return self.lossless

    @property
    def counts(self) -> dict[str, int]:
        return {
            "preserved": len(self.preserved),
            "transformed": len(self.transformed),
            "deferred": len(self.deferred),
            "unsupported": len(self.unsupported),
        }

    @property
    def covered_sections(self) -> tuple[str, ...]:
        sections = {
            entry.path.split(".", 1)[0].split("[", 1)[0]
            for entry in self.entries
        }
        return tuple(sorted(sections))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_api_version": self.source_api_version,
            "source_sha256": self.source_sha256,
            "lossless": self.lossless,
            "reversible": self.reversible,
            "counts": self.counts,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompatibilityReport":
        return cls(
            source_api_version=str(value["source_api_version"]),
            source_sha256=str(value["source_sha256"]),
            entries=tuple(
                CompatibilityEntry.from_dict(item)
                for item in value.get("entries", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class CompatibilityWarning:
    """Backward-compatible human-facing warning returned by the old API."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    system: SystemModel
    warnings: tuple[CompatibilityWarning, ...] = ()
    report: CompatibilityReport = field(
        default_factory=lambda: CompatibilityReport(
            source_api_version="unknown",
            source_sha256="",
        )
    )

    @property
    def lossless(self) -> bool:
        return self.report.lossless

    @property
    def reversible(self) -> bool:
        return self.report.reversible


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True, mode="json")
    return value


def _canonical_manifest_dict(manifest: PipelineManifest) -> dict[str, Any]:
    return manifest.model_dump(
        by_alias=True,
        exclude_none=True,
        mode="json",
    )


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _snapshot_manifest(manifest: PipelineManifest) -> tuple[str, str]:
    payload = _canonical_json(_canonical_manifest_dict(manifest))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return payload, digest


def _legacy_endpoint(
    value: str,
    *,
    node_names: set[str],
    graph_name: str,
) -> str:
    instance, separator, port = value.partition(".")
    if not separator:
        return value
    if instance in node_names:
        return f"{graph_name}/{instance}.{port}"
    return value


def _entry(
    entries: list[CompatibilityEntry],
    path: str,
    disposition: CompatibilityDisposition,
    target: str,
    message: str,
) -> None:
    entries.append(
        CompatibilityEntry(
            path=path,
            disposition=disposition,
            target=target,
            message=message,
        )
    )


def _build_report_entries(
    manifest: PipelineManifest,
    *,
    graph_name: str,
) -> list[CompatibilityEntry]:
    entries: list[CompatibilityEntry] = []

    _entry(
        entries,
        "apiVersion",
        "transformed",
        "extensions.legacy_pipeline.apiVersion",
        "Pipeline API version is retained as migration provenance.",
    )
    _entry(
        entries,
        "kind",
        "transformed",
        "kind",
        "Pipeline is intentionally transformed into System.",
    )
    _entry(
        entries,
        "metadata",
        "transformed",
        "name,description",
        "Pipeline metadata is promoted to canonical System identity.",
    )
    _entry(
        entries,
        "runtime",
        "deferred",
        "extensions.legacy_pipeline.runtime",
        "Runtime engine, telemetry, memory and shutdown semantics are retained "
        "for the future execution compatibility layer.",
    )

    for name in manifest.sessions:
        _entry(
            entries,
            f"sessions.{name}",
            "transformed",
            f"resources.{name}",
            "Legacy Session becomes a ResourceInstance with legacy_role=session.",
        )

    for name in manifest.resources:
        _entry(
            entries,
            f"resources.{name}",
            "transformed",
            f"resources.{name}",
            "Provider resource becomes a ResourceInstance.",
        )

    for name in manifest.applications:
        _entry(
            entries,
            f"applications.{name}",
            "transformed",
            f"applications.{name}",
            "External application becomes an ApplicationInstance.",
        )

    for name in manifest.nodes:
        _entry(
            entries,
            f"nodes.{name}",
            "transformed",
            f"graphs.{graph_name}.nodes.{name}",
            "Pipeline node becomes a NodeInstance.",
        )
        _entry(
            entries,
            f"nodes.{name}.runtime_semantics",
            "deferred",
            f"graphs.{graph_name}.nodes.{name}.extensions.legacy",
            "Inputs/outputs overrides, synchronization, execution, failure, "
            "health, resource limits and memory policy are retained for 2.6.",
        )

    for index, edge in enumerate(manifest.edges):
        if edge.transport is None:
            target = f"graphs.{graph_name}.connections[{index}]"
            message = "Local Pipeline edge becomes a Graph Connection."
        else:
            target = "links"
            message = (
                "Transport-backed Pipeline edge becomes an explicit SystemLink."
            )
        _entry(
            entries,
            f"edges[{index}]",
            "transformed",
            target,
            message,
        )
        _entry(
            entries,
            f"edges[{index}].queue_memory",
            "deferred",
            f"{target}.extensions.legacy",
            "Queue and memory-domain execution policy is retained for 2.6.",
        )

    for index, _link in enumerate(manifest.links):
        _entry(
            entries,
            f"links[{index}]",
            "transformed",
            "links",
            "Legacy external link becomes a SystemLink.",
        )

    _entry(
        entries,
        "streams",
        "deferred",
        "extensions.legacy_pipeline.streams",
        "Stream serving/access/TLS semantics remain operations-layer data.",
    )
    _entry(
        entries,
        "fragments",
        "deferred",
        "extensions.legacy_pipeline.fragments",
        "Fragments are retained until reusable/hierarchical Graphs are canonical.",
    )
    _entry(
        entries,
        "recording",
        "deferred",
        "extensions.legacy_pipeline.recording",
        "Recording remains operations-layer data.",
    )
    _entry(
        entries,
        "security",
        "deferred",
        "extensions.legacy_pipeline.security",
        "Plugin/security policy remains operations-layer data.",
    )
    _entry(
        entries,
        "placement",
        "transformed",
        "targets,node.target",
        "Legacy placement names become Target declarations and node assignments.",
    )

    return entries


def pipeline_manifest_to_system(
    manifest: PipelineManifest,
    *,
    graph_name: str = "main",
) -> CompatibilityResult:
    """Convert one 2.x PipelineManifest into a backend-neutral SystemModel.

    The migration is loss-aware and reversible at the semantic manifest level.
    Runtime/operations fields that do not yet have canonical 2.5 equivalents
    are retained both in readable ``extensions`` and in an integrity-protected
    canonical source snapshot.
    """

    warnings: list[CompatibilityWarning] = []
    source_manifest_json, source_sha256 = _snapshot_manifest(manifest)
    report = CompatibilityReport(
        source_api_version=manifest.api_version,
        source_sha256=source_sha256,
        entries=tuple(
            _build_report_entries(manifest, graph_name=graph_name)
        ),
    )

    resources: list[ResourceInstance] = []
    for name, session in manifest.sessions.items():
        resources.append(
            ResourceInstance(
                name=name,
                uses=session.uses,
                parameters=dict(session.parameters),
                extensions={"legacy_role": "session"},
            )
        )

    for name, resource in manifest.resources.items():
        resources.append(
            ResourceInstance(
                name=name,
                uses=resource.uses,
                parameters=dict(resource.parameters),
                bindings=dict(resource.bindings),
                extensions={"legacy_role": "resource"},
            )
        )

    target_names = {
        manifest.placement.default,
        *manifest.placement.nodes.values(),
        *(
            node.placement
            for node in manifest.nodes.values()
            if node.placement is not None
        ),
    }
    targets = tuple(
        Target(
            name=name,
            kind="placement",
            properties={"legacy": True},
        )
        for name in sorted(name for name in target_names if name)
    )

    nodes = []
    for name, node in manifest.nodes.items():
        target = (
            node.placement
            or manifest.placement.nodes.get(name)
            or manifest.placement.default
        )
        nodes.append(
            {
                "name": name,
                "uses": node.uses,
                "parameters": dict(node.parameters),
                "resources": dict(node.bindings),
                "target": target,
                "extensions": {
                    "legacy": {
                        "inputs": dict(node.inputs),
                        "outputs": dict(node.outputs),
                        "synchronization": _dump(node.synchronization),
                        "execution": _dump(node.execution),
                        "failure": _dump(node.failure),
                        "health": _dump(node.health),
                        "resource_limits": _dump(node.resources),
                        "memory": _dump(node.memory),
                    }
                },
            }
        )

    node_names = set(manifest.nodes)
    local_connections: list[Connection] = []
    links: list[SystemLink] = []

    for edge in manifest.edges:
        if edge.transport is None:
            local_connections.append(
                Connection(
                    **{
                        "from": edge.source,
                        "to": edge.target,
                        "extensions": {
                            "legacy": {
                                "queue": _dump(edge.queue),
                                "memory": _dump(edge.memory),
                            }
                        },
                    }
                )
            )
            continue

        links.append(
            SystemLink(
                **{
                    "from": _legacy_endpoint(
                        edge.source,
                        node_names=node_names,
                        graph_name=graph_name,
                    ),
                    "to": _legacy_endpoint(
                        edge.target,
                        node_names=node_names,
                        graph_name=graph_name,
                    ),
                    "uses": edge.transport.uses,
                    "parameters": dict(edge.transport.parameters),
                    "extensions": {
                        "legacy": {
                            "queue": _dump(edge.queue),
                            "memory": _dump(edge.memory),
                            "source": "transport_edge",
                        }
                    },
                }
            )
        )

    for link in manifest.links:
        links.append(
            SystemLink(
                **{
                    "from": _legacy_endpoint(
                        link.source,
                        node_names=node_names,
                        graph_name=graph_name,
                    ),
                    "to": _legacy_endpoint(
                        link.target,
                        node_names=node_names,
                        graph_name=graph_name,
                    ),
                    "uses": link.uses,
                    "parameters": dict(link.parameters),
                    "extensions": {"legacy": {"source": "external_link"}},
                }
            )
        )

    applications = tuple(
        ApplicationInstance(
            name=name,
            uses=application.uses,
            parameters=dict(application.parameters),
            resources=dict(application.bindings),
            target=manifest.placement.default,
        )
        for name, application in manifest.applications.items()
    )

    if manifest.fragments:
        warnings.append(
            CompatibilityWarning(
                "COMPAT201",
                "legacy fragments are retained in SystemModel.extensions and are "
                "not yet promoted to reusable Graph definitions",
            )
        )

    if manifest.streams.exports:
        warnings.append(
            CompatibilityWarning(
                "COMPAT202",
                "legacy stream exports are retained in SystemModel.extensions and "
                "are not yet canonical System links/artifacts",
            )
        )

    if manifest.recording.enabled:
        warnings.append(
            CompatibilityWarning(
                "COMPAT203",
                "legacy recording policy is retained in SystemModel.extensions; "
                "first-class recording policy belongs to a later operations layer",
            )
        )

    system = SystemModel(
        name=manifest.metadata.name,
        description=manifest.metadata.description,
        resources=tuple(resources),
        applications=applications,
        graphs=(
            Graph(
                name=graph_name,
                nodes=tuple(nodes),
                connections=tuple(local_connections),
            ),
        ),
        links=tuple(links),
        targets=targets,
        extensions={
            "legacy_pipeline": {
                "apiVersion": manifest.api_version,
                "runtime": _dump(manifest.runtime),
                "streams": _dump(manifest.streams),
                "fragments": {
                    name: _dump(fragment)
                    for name, fragment in manifest.fragments.items()
                },
                "recording": _dump(manifest.recording),
                "security": _dump(manifest.security),
                "placement": _dump(manifest.placement),
                # Stored as canonical JSON string rather than a nested mapping:
                # system_to_canonical() intentionally prunes empty containers,
                # while this integrity snapshot must remain byte-stable across
                # System YAML/JSON round-trips.
                "source_manifest_json": source_manifest_json,
                "source_manifest_sha256": source_sha256,
                "compatibility_report": report.to_dict(),
            }
        },
    )

    return CompatibilityResult(
        system=system,
        warnings=tuple(warnings),
        report=report,
    )


def _legacy_extensions(system: SystemModel) -> Mapping[str, Any]:
    legacy = system.extensions.get("legacy_pipeline")
    if not isinstance(legacy, Mapping):
        raise CompatibilityError(
            "System does not contain a legacy Pipeline compatibility snapshot",
            code="COMPAT401",
        )
    return legacy


def compatibility_report_from_system(
    system: SystemModel,
) -> CompatibilityReport:
    """Recover the persisted compatibility report from a converted System."""

    legacy = _legacy_extensions(system)
    value = legacy.get("compatibility_report")
    if not isinstance(value, Mapping):
        raise CompatibilityError(
            "System does not contain a persisted compatibility report",
            code="COMPAT402",
        )
    return CompatibilityReport.from_dict(value)


def restore_pipeline_manifest(
    system: SystemModel,
    *,
    verify_digest: bool = True,
) -> PipelineManifest:
    """Restore the canonical 2.x PipelineManifest captured during migration.

    This restores the validated semantic manifest, not the original source file
    formatting/comments.
    """

    legacy = _legacy_extensions(system)
    payload = legacy.get("source_manifest_json")
    expected_digest = legacy.get("source_manifest_sha256")

    if not isinstance(payload, str) or not payload:
        raise CompatibilityError(
            "legacy compatibility snapshot is missing source_manifest_json",
            code="COMPAT403",
        )
    if not isinstance(expected_digest, str) or not expected_digest:
        raise CompatibilityError(
            "legacy compatibility snapshot is missing source_manifest_sha256",
            code="COMPAT403",
        )

    actual_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if verify_digest and actual_digest != expected_digest:
        raise CompatibilityError(
            "legacy Pipeline snapshot digest mismatch; compatibility data was "
            "modified or corrupted",
            code="COMPAT405",
        )

    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CompatibilityError(
            f"legacy Pipeline snapshot is not valid JSON: {exc}",
            code="COMPAT406",
        ) from exc

    try:
        return PipelineManifest.model_validate(raw)
    except Exception as exc:
        raise CompatibilityError(
            f"legacy Pipeline snapshot no longer validates: {exc}",
            code="COMPAT407",
        ) from exc


__all__ = [
    "CompatibilityDisposition",
    "CompatibilityEntry",
    "CompatibilityError",
    "CompatibilityReport",
    "CompatibilityResult",
    "CompatibilityWarning",
    "compatibility_report_from_system",
    "pipeline_manifest_to_system",
    "restore_pipeline_manifest",
]
