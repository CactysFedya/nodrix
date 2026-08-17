"""Authoring resolution for Nodrix System sources.

A System Source may compose structural System Modules through ``imports``.
Authoring constructs disappear before canonical SystemModel validation.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..errors import NodrixError


SYSTEM_MODULE_SCHEMA = "nodrix.system-module/v1"

_SYSTEM_STRUCTURE_FIELDS = (
    "resources",
    "applications",
    "graphs",
    "links",
    "targets",
    "artifacts",
)

_SYSTEM_MODULE_FIELDS = frozenset({
    "schema",
    "imports",
    *_SYSTEM_STRUCTURE_FIELDS,
})


class SystemSourceError(NodrixError):
    """A human-facing System Source cannot be resolved."""


@dataclass(frozen=True, slots=True)
class SystemSourceResolution:
    """Result of resolving one System authoring source."""

    document: Any
    source: Path | None
    sources: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class SystemConfigResolution:
    """Resolved semantic System configuration."""

    config: dict[str, Any]
    sources: tuple[Path, ...]


def _load_module(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(
            path.read_text(encoding="utf-8")
        )
    except (OSError, yaml.YAMLError) as exc:
        raise SystemSourceError(
            f"Cannot load System Module {path}: {exc}"
        ) from exc

    if not isinstance(raw, Mapping):
        raise SystemSourceError(
            f"System Module must contain a YAML mapping: {path}"
        )

    document = dict(raw)

    if document.get("schema") != SYSTEM_MODULE_SCHEMA:
        raise SystemSourceError(
            f"System Module {path} must declare "
            f"schema: {SYSTEM_MODULE_SCHEMA}"
        )

    unknown = sorted(
        set(document) - _SYSTEM_MODULE_FIELDS
    )
    if unknown:
        raise SystemSourceError(
            f"System Module {path} has unsupported fields: "
            + ", ".join(unknown)
        )

    return document


def _resolve_import_paths(
    value: Any,
    *,
    base_dir: Path,
    owner: Path,
) -> tuple[Path, ...]:
    if value is None:
        return ()

    if not isinstance(value, list):
        raise SystemSourceError(
            f"imports in {owner} must be a list of YAML paths"
        )

    resolved: list[Path] = []

    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            raise SystemSourceError(
                f"imports in {owner} must contain non-empty path strings"
            )

        path = Path(raw).expanduser()

        if not path.is_absolute():
            path = base_dir / path

        path = path.resolve()

        if not path.is_file():
            raise SystemSourceError(
                f"Imported System Module does not exist: {path}"
            )

        resolved.append(path)

    return tuple(resolved)


def _merge_structure(
    target: dict[str, Any],
    source: Mapping[str, Any],
    *,
    owner: str,
) -> None:
    for field in _SYSTEM_STRUCTURE_FIELDS:
        if field not in source:
            continue

        incoming = source[field]

        if not isinstance(incoming, list):
            raise SystemSourceError(
                f"{field} in {owner} must be a list"
            )

        current = target.setdefault(
            field,
            [],
        )

        if not isinstance(current, list):
            raise SystemSourceError(
                f"Cannot compose non-list System field {field}"
            )

        names = {
            str(item["name"])
            for item in current
            if isinstance(item, Mapping)
            and item.get("name")
        }

        for item in incoming:
            if (
                isinstance(item, Mapping)
                and item.get("name")
            ):
                name = str(item["name"])

                if name in names:
                    raise SystemSourceError(
                        f"Duplicate {field} name {name!r} "
                        f"while composing {owner}"
                    )

                names.add(name)

            current.append(
                deepcopy(item)
            )


def _resolve_module(
    path: Path,
    *,
    stack: tuple[Path, ...],
    seen: set[Path],
) -> tuple[dict[str, Any], tuple[Path, ...]]:
    if path in stack:
        chain = " -> ".join(
            str(item)
            for item in (*stack, path)
        )
        raise SystemSourceError(
            f"Recursive System Module import: {chain}"
        )

    if path in seen:
        raise SystemSourceError(
            f"System Module imported more than once: {path}"
        )

    seen.add(path)

    document = _load_module(path)

    imports = _resolve_import_paths(
        document.get("imports"),
        base_dir=path.parent,
        owner=path,
    )

    resolved: dict[str, Any] = {}
    sources: list[Path] = [path]

    next_stack = (*stack, path)

    for imported in imports:
        child, child_sources = _resolve_module(
            imported,
            stack=next_stack,
            seen=seen,
        )

        _merge_structure(
            resolved,
            child,
            owner=str(imported),
        )

        sources.extend(
            child_sources
        )

    local = dict(document)
    local.pop("schema", None)
    local.pop("imports", None)

    _merge_structure(
        resolved,
        local,
        owner=str(path),
    )

    return (
        resolved,
        tuple(sources),
    )


_CONFIG_REFERENCE_PREFIX = "${config."


def _config_reference_path(
    value: str,
) -> str | None:
    """Return the dotted path for one exact Config reference."""

    if not value.startswith(_CONFIG_REFERENCE_PREFIX):
        return None

    if not value.endswith("}"):
        return None

    path = value[
        len(_CONFIG_REFERENCE_PREFIX):-1
    ]

    if (
        not path
        or any(
            not part
            for part in path.split(".")
        )
    ):
        raise SystemSourceError(
            f"Invalid System Config reference: {value!r}"
        )

    return path


def _lookup_config_value(
    config: Mapping[str, Any],
    path: str,
    *,
    location: str,
) -> Any:
    """Resolve one dotted path from semantic System Config."""

    current: Any = config

    for part in path.split("."):
        if (
            not isinstance(current, Mapping)
            or part not in current
        ):
            raise SystemSourceError(
                f"Unknown System Config path {path!r} "
                f"referenced at {location}"
            )

        current = current[part]

    return deepcopy(current)


def _bind_config_references(
    value: Any,
    *,
    config: Mapping[str, Any],
    location: str = "$",
) -> Any:
    """Replace exact ``${config.*}`` references with typed values."""

    if isinstance(value, str):
        path = _config_reference_path(
            value
        )

        if path is not None:
            return _lookup_config_value(
                config,
                path,
                location=location,
            )

        if _CONFIG_REFERENCE_PREFIX in value:
            raise SystemSourceError(
                "Embedded System Config interpolation is not supported "
                f"at {location}: {value!r}; "
                "use one exact ${config.path} reference"
            )

        return value

    if isinstance(value, Mapping):
        return {
            key: _bind_config_references(
                item,
                config=config,
                location=f"{location}.{key}",
            )
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            _bind_config_references(
                item,
                config=config,
                location=f"{location}[{index}]",
            )
            for index, item in enumerate(value)
        ]

    return deepcopy(value)


def resolve_system_source_document(
    raw: Any,
    *,
    source: str | Path | None = None,
) -> SystemSourceResolution:
    """Resolve one human-facing System Source.

    ``imports`` composes structural ``nodrix.system-module/v1`` documents.
    ``config`` resolves ordered semantic Config files.

    Exact ``${config.path}`` references are replaced with their original typed
    values after structural composition. Authoring-only fields disappear before
    canonical SystemModel validation.
    """

    source_path = (
        Path(source).expanduser().resolve()
        if source is not None
        else None
    )

    if not isinstance(raw, Mapping):
        return SystemSourceResolution(
            document=raw,
            source=source_path,
            sources=(
                (source_path,)
                if source_path is not None
                else ()
            ),
        )

    source_document = deepcopy(
        dict(raw)
    )

    imports_value = source_document.pop(
        "imports",
        None,
    )

    config_value = source_document.pop(
        "config",
        None,
    )

    if (
        source_path is None
        and (
            imports_value is not None
            or config_value is not None
        )
    ):
        raise SystemSourceError(
            "System imports/config require a file-backed source "
            "so relative paths can be resolved"
        )

    resolved: dict[str, Any] = {}

    sources: list[Path] = (
        [source_path]
        if source_path is not None
        else []
    )

    if imports_value is not None:
        assert source_path is not None

        imports = _resolve_import_paths(
            imports_value,
            base_dir=source_path.parent,
            owner=source_path,
        )

        seen: set[Path] = set()

        for imported in imports:
            module, module_sources = _resolve_module(
                imported,
                stack=(source_path,),
                seen=seen,
            )

            _merge_structure(
                resolved,
                module,
                owner=str(imported),
            )

            sources.extend(
                module_sources
            )

    root_structure = {
        field: source_document.pop(field)
        for field in _SYSTEM_STRUCTURE_FIELDS
        if field in source_document
    }

    resolved.update(
        source_document
    )

    _merge_structure(
        resolved,
        root_structure,
        owner=(
            str(source_path)
            if source_path is not None
            else "<memory>"
        ),
    )

    config_resolution = resolve_system_config(
        config_value,
        base_dir=(
            source_path.parent
            if source_path is not None
            else None
        ),
    )

    resolved = _bind_config_references(
        resolved,
        config=config_resolution.config,
    )

    sources.extend(
        config_resolution.sources
    )

    return SystemSourceResolution(
        document=resolved,
        source=source_path,
        sources=tuple(sources),
    )


def _deep_merge_config(
    base: Mapping[str, Any],
    overlay: Mapping[str, Any],
    *,
    source: Path,
) -> dict[str, Any]:
    """Merge one Config mapping over another deterministically."""

    result = deepcopy(dict(base))

    for key, value in overlay.items():
        if not isinstance(key, str):
            raise SystemSourceError(
                f"Config keys must be strings in {source}: {key!r}"
            )

        current = result.get(key)

        if (
            isinstance(current, Mapping)
            and isinstance(value, Mapping)
        ):
            result[key] = _deep_merge_config(
                current,
                value,
                source=source,
            )
        else:
            result[key] = deepcopy(value)

    return result


def _load_config_document(
    path: Path,
) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(
            path.read_text(encoding="utf-8")
        )
    except (OSError, yaml.YAMLError) as exc:
        raise SystemSourceError(
            f"Cannot load System Config {path}: {exc}"
        ) from exc

    if raw is None:
        return {}

    if not isinstance(raw, Mapping):
        raise SystemSourceError(
            f"System Config must contain a YAML mapping: {path}"
        )

    return _deep_merge_config(
        {},
        raw,
        source=path,
    )


def resolve_system_config(
    references: Any,
    *,
    base_dir: str | Path | None = None,
) -> SystemConfigResolution:
    """Resolve ordered Config files into one semantic configuration.

    Config documents are plain YAML mappings, not canonical Definitions.

    Files are merged from left to right. Mapping values merge recursively;
    scalar and list values are replaced completely by later documents.
    """

    if references is None:
        return SystemConfigResolution(
            config={},
            sources=(),
        )

    if isinstance(
        references,
        (str, Path),
    ):
        items = (references,)
    elif isinstance(
        references,
        (list, tuple),
    ):
        items = tuple(references)
    else:
        raise SystemSourceError(
            "System config references must be a YAML path "
            "or an ordered list of YAML paths"
        )

    root = (
        Path(base_dir).expanduser().resolve()
        if base_dir is not None
        else Path.cwd().resolve()
    )

    config: dict[str, Any] = {}
    sources: list[Path] = []

    for reference in items:
        if not isinstance(
            reference,
            (str, Path),
        ):
            raise SystemSourceError(
                "System config references must contain only YAML paths"
            )

        path = Path(reference).expanduser()

        if not path.is_absolute():
            path = root / path

        path = path.resolve()

        if not path.is_file():
            raise SystemSourceError(
                f"System Config does not exist: {path}"
            )

        document = _load_config_document(
            path
        )

        config = _deep_merge_config(
            config,
            document,
            source=path,
        )

        sources.append(path)

    return SystemConfigResolution(
        config=config,
        sources=tuple(sources),
    )


__all__ = [
    "SYSTEM_MODULE_SCHEMA",
    "SystemConfigResolution",
    "SystemSourceError",
    "SystemSourceResolution",
    "resolve_system_config",
    "resolve_system_source_document",
]
