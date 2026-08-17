"""Serialization and parsing for the canonical ``nodrix.system/v1`` format."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Literal, Mapping, Iterable

from pydantic import ValidationError
import yaml

from ..errors import NodrixError
from .model import SYSTEM_MODEL_API_VERSION, SystemModel
from .source import (
    SystemConfigOverlay,
    resolve_system_source_document,
)


SYSTEM_MODEL_KIND = "System"
SYSTEM_MODEL_SCHEMA_ID = "urn:nodrix:schema:system:v1"
SystemDocumentFormat = Literal["yaml", "json"]

_TOP_LEVEL_ORDER = (
    "apiVersion",
    "kind",
    "name",
    "description",
    "resources",
    "applications",
    "graphs",
    "links",
    "targets",
    "artifacts",
    "policies",
    "metadata",
    "extensions",
)


class SystemFormatError(NodrixError):
    """A System document cannot be parsed or validated."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "SYSFMT000",
        location: str = "",
    ) -> None:
        self.code = code
        self.location = location
        prefix = code if not location else f"{code} {location}"
        super().__init__(f"{prefix}: {message}")


@dataclass(frozen=True, slots=True)
class SystemResolutionDetails:
    """Authoring inputs used to produce one canonical System."""

    sources: tuple[Path, ...] = ()
    module_sources: tuple[Path, ...] = ()
    config_sources: tuple[Path, ...] = ()
    config_overlay_sources: tuple[Path, ...] = ()
    config_provenance: dict[str, Path] = field(
        default_factory=dict
    )

    def source_for_config(
        self,
        path: str,
    ) -> Path | None:
        """Return the winning Config source for one dotted path."""

        return self.config_provenance.get(
            path
        )


@dataclass(frozen=True, slots=True)
class SystemLoadResult:
    system: SystemModel
    canonical: dict[str, Any]
    path: Path
    format: SystemDocumentFormat
    resolution: SystemResolutionDetails = field(
        default_factory=SystemResolutionDetails
    )


def _normalize_format(
    value: str | None,
    *,
    path: Path | None = None,
    default: SystemDocumentFormat = "yaml",
) -> SystemDocumentFormat:
    if value is None:
        if path is None:
            return default
        suffix = path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            return "yaml"
        if suffix == ".json":
            return "json"
        raise SystemFormatError(
            "cannot infer document format; use .yaml, .yml, or .json",
            code="SYSFMT004",
            location=str(path),
        )

    normalized = value.lower().lstrip(".")
    if normalized == "yml":
        normalized = "yaml"
    if normalized not in {"yaml", "json"}:
        raise SystemFormatError(
            f"unsupported document format {value!r}; expected 'yaml' or 'json'",
            code="SYSFMT004",
        )
    return normalized  # type: ignore[return-value]


def _decode_document(text: str, format: SystemDocumentFormat) -> Any:
    try:
        if format == "json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SystemFormatError(
            f"cannot parse {format.upper()} document: {exc}",
            code="SYSFMT005",
        ) from exc


def _validate_header(raw: Any) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise SystemFormatError(
            "System document must be a mapping/object",
            code="SYSFMT001",
        )

    if "apiVersion" not in raw:
        raise SystemFormatError(
            "missing required field 'apiVersion'",
            code="SYSFMT002",
            location="apiVersion",
        )
    api_version = raw["apiVersion"]
    if api_version != SYSTEM_MODEL_API_VERSION:
        raise SystemFormatError(
            f"unsupported System apiVersion {api_version!r}; "
            f"expected {SYSTEM_MODEL_API_VERSION!r}",
            code="SYSFMT003",
            location="apiVersion",
        )

    if "kind" not in raw:
        raise SystemFormatError(
            "missing required field 'kind'",
            code="SYSFMT002",
            location="kind",
        )
    kind = raw["kind"]
    if kind != SYSTEM_MODEL_KIND:
        raise SystemFormatError(
            f"unsupported document kind {kind!r}; expected {SYSTEM_MODEL_KIND!r}",
            code="SYSFMT003",
            location="kind",
        )

    return raw


def _prune_empty(value: Any) -> Any:
    """Remove default empty containers while keeping semantic scalar values."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(value, key=str):
            cleaned = _prune_empty(value[key])
            if cleaned is None:
                continue
            if isinstance(cleaned, (dict, list)) and not cleaned:
                continue
            result[str(key)] = cleaned
        return result

    if isinstance(value, (list, tuple)):
        return [_prune_empty(item) for item in value]

    return value


def system_to_canonical(system: SystemModel) -> dict[str, Any]:
    """Return the normalized serializable representation of a System.

    Model aliases are used (``apiVersion``, ``from``, ``to``), ``None`` and
    default-empty containers are omitted, free-form mapping keys are sorted,
    and the top-level field order remains human-friendly and stable.
    """

    raw = system.model_dump(
        by_alias=True,
        exclude_none=True,
        mode="json",
    )
    cleaned = _prune_empty(raw)
    if not isinstance(cleaned, dict):
        raise TypeError("SystemModel did not serialize to a mapping")

    canonical: dict[str, Any] = {}
    for key in _TOP_LEVEL_ORDER:
        if key in cleaned:
            canonical[key] = cleaned.pop(key)
    for key in sorted(cleaned):
        canonical[key] = cleaned[key]
    return canonical


def _validate_document(raw: Any) -> SystemModel:
    mapping = _validate_header(raw)
    try:
        return SystemModel.model_validate(mapping)
    except ValidationError as exc:
        raise SystemFormatError(
            f"System document does not match {SYSTEM_MODEL_API_VERSION}: {exc}",
            code="SYSFMT006",
        ) from exc


def loads_system(
    text: str,
    *,
    format: str = "yaml",
    config_overlays: Iterable[SystemConfigOverlay] = (),
) -> SystemModel:
    """Load a SystemModel from YAML or JSON text."""

    resolved_format = _normalize_format(format)
    raw = _decode_document(text, resolved_format)
    resolved = resolve_system_source_document(
        raw,
        config_overlays=config_overlays,
    )
    return _validate_document(resolved.document)


def load_system_details(
    path: str | Path,
    *,
    format: str | None = None,
    config_overlays: Iterable[SystemConfigOverlay] = (),
) -> SystemLoadResult:
    """Load a System document and return its normalized representation."""

    system_path = Path(path).expanduser().resolve()
    if not system_path.exists():
        raise SystemFormatError(
            "System file does not exist",
            code="SYSFMT007",
            location=str(system_path),
        )
    if not system_path.is_file():
        raise SystemFormatError(
            "System path is not a file",
            code="SYSFMT007",
            location=str(system_path),
        )

    resolved_format = _normalize_format(format, path=system_path)
    try:
        text = system_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemFormatError(
            f"cannot read System file: {exc}",
            code="SYSFMT007",
            location=str(system_path),
        ) from exc

    raw = _decode_document(text, resolved_format)
    resolved = resolve_system_source_document(
        raw,
        source=system_path,
        config_overlays=config_overlays,
    )
    system = _validate_document(resolved.document)
    return SystemLoadResult(
        system=system,
        canonical=system_to_canonical(system),
        path=system_path,
        format=resolved_format,
        resolution=SystemResolutionDetails(
            sources=resolved.sources,
            module_sources=resolved.module_sources,
            config_sources=resolved.config_sources,
            config_overlay_sources=(
                resolved.config_overlay_sources
            ),
            config_provenance=dict(
                resolved.config_provenance
            ),
        ),
    )


def load_system(
    path: str | Path,
    *,
    format: str | None = None,
    config_overlays: Iterable[SystemConfigOverlay] = (),
) -> SystemModel:
    """Load a SystemModel from a .yaml/.yml/.json document."""

    return load_system_details(
        path,
        format=format,
        config_overlays=config_overlays,
    ).system


def dumps_system(
    system: SystemModel,
    *,
    format: str = "yaml",
) -> str:
    """Serialize a SystemModel using the canonical representation."""

    resolved_format = _normalize_format(format)
    data = system_to_canonical(system)

    if resolved_format == "json":
        return json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        ) + "\n"

    return yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def dump_system(
    system: SystemModel,
    path: str | Path,
    *,
    format: str | None = None,
) -> None:
    """Write a canonical System document.

    The format is inferred from .yaml/.yml/.json unless explicitly supplied.
    """

    destination = Path(path).expanduser()
    resolved_format = _normalize_format(format, path=destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.write_text(
            dumps_system(system, format=resolved_format),
            encoding="utf-8",
        )
    except OSError as exc:
        raise SystemFormatError(
            f"cannot write System file: {exc}",
            code="SYSFMT008",
            location=str(destination),
        ) from exc


def system_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for the current canonical System format."""

    schema = SystemModel.model_json_schema(by_alias=True)
    schema["$id"] = SYSTEM_MODEL_SCHEMA_ID
    schema["title"] = "Nodrix System Model v1"
    return schema


def dump_system_schema(path: str | Path) -> None:
    """Write the current System JSON Schema."""

    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            system_json_schema(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "SYSTEM_MODEL_KIND",
    "SYSTEM_MODEL_SCHEMA_ID",
    "SystemDocumentFormat",
    "SystemFormatError",
    "SystemLoadResult",
    "SystemResolutionDetails",
    "dump_system",
    "dump_system_schema",
    "dumps_system",
    "load_system",
    "load_system_details",
    "loads_system",
    "system_json_schema",
    "system_to_canonical",
]
