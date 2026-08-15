from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError
import yaml

from .errors import ManifestError
from .manifest_model import PipelineManifest, _ENV_RE, _expand_env
from .manifest_parser import (
    _apply_block_overrides,
    _apply_profile,
    _normalize_and_expand_fragments,
    _normalize_compact,
    _set_path,
    canonical_config_path,
)


@dataclass(slots=True)
class ManifestDiagnostic:
    severity: str
    code: str
    message: str
    location: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "location": self.location,
        }


def _compatibility_diagnostics(raw: Mapping[str, Any]) -> tuple[ManifestDiagnostic, ...]:
    diagnostics: list[ManifestDiagnostic] = []
    for section in ("sessions", "resources", "applications", "nodes"):
        values = raw.get(section)
        if not isinstance(values, Mapping):
            continue
        for name, value in values.items():
            if isinstance(value, Mapping) and "use" in value:
                diagnostics.append(
                    ManifestDiagnostic(
                        severity="warning",
                        code="W214",
                        message=(
                            "Deprecated field 'use'; use 'uses' instead. "
                            "The alias will be removed in Plyctl 3.0."
                        ),
                        location=f"{section}.{name}.use",
                    )
                )
    edges = raw.get("edges")
    if isinstance(edges, list):
        for index, edge in enumerate(edges):
            transport = edge.get("transport") if isinstance(edge, Mapping) else None
            if isinstance(transport, Mapping) and "use" in transport:
                diagnostics.append(
                    ManifestDiagnostic(
                        severity="warning",
                        code="W214",
                        message=(
                            "Deprecated field 'use'; use 'uses' instead. "
                            "The alias will be removed in Plyctl 3.0."
                        ),
                        location=f"edges[{index}].transport.use",
                    )
                )
    links = raw.get("links")
    if isinstance(links, list):
        for index, link in enumerate(links):
            if isinstance(link, Mapping) and "use" in link:
                diagnostics.append(
                    ManifestDiagnostic(
                        severity="warning",
                        code="W214",
                        message=(
                            "Deprecated field 'use'; use 'uses' instead. "
                            "The alias will be removed in Plyctl 3.0."
                        ),
                        location=f"links[{index}].use",
                    )
                )
        if links:
            diagnostics.append(
                ManifestDiagnostic(
                    severity="warning",
                    code="W215",
                    message=(
                        "Deprecated top-level 'links'; attach the external "
                        "provider as edges[].transport instead. The alias "
                        "will be removed in Plyctl 3.0."
                    ),
                    location="links",
                )
            )
    return tuple(diagnostics)


@dataclass(slots=True)
class ManifestLoadResult:
    manifest: PipelineManifest
    canonical: dict[str, Any]
    sources: dict[str, str]
    path: Path
    block_files: dict[str, Path]
    diagnostics: tuple[ManifestDiagnostic, ...] = ()


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
        diagnostics = list(_compatibility_diagnostics(loaded))
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
    for block_name, block_path in block_files.items():
        try:
            raw_block = yaml.safe_load(block_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(raw_block, Mapping) and "use" in raw_block:
            diagnostics.append(
                ManifestDiagnostic(
                    severity="warning",
                    code="W214",
                    message=(
                        "Deprecated field 'use'; use 'uses' instead. The "
                        "alias will be removed in Plyctl 3.0."
                    ),
                    location=f"blocks.{block_name}.use",
                )
            )
    return ManifestLoadResult(
        manifest,
        resolved,
        sources,
        manifest_path,
        block_files,
        tuple(diagnostics),
    )


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
