from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

import yaml

from .manifest import PipelineManifest, load_manifest_details


MIGRATION_SCHEMA = "nodrix.migration/v1"


def _legacy_use_paths(raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        return []
    result: list[str] = []
    for section in ("sessions", "resources", "applications", "nodes"):
        values = raw.get(section)
        if not isinstance(values, dict):
            continue
        for name, value in values.items():
            if isinstance(value, dict) and "use" in value:
                result.append(f"{section}.{name}.use")
    links = raw.get("links")
    if isinstance(links, list):
        for index, value in enumerate(links):
            if isinstance(value, dict) and "use" in value:
                result.append(f"links[{index}].use")
    edges = raw.get("edges")
    if isinstance(edges, list):
        for index, value in enumerate(edges):
            transport = value.get("transport") if isinstance(value, dict) else None
            if isinstance(transport, dict) and "use" in transport:
                result.append(f"edges[{index}].transport.use")
    return result


def _backup_path(source: Path) -> Path:
    candidate = source.with_name(source.name + ".v1.bak")
    index = 1
    while candidate.exists():
        candidate = source.with_name(source.name + f".v1.bak.{index}")
        index += 1
    return candidate


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            Path(temporary).unlink()
        except OSError:
            pass
        raise


def prepare_v2_manifest(source: str | Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    source_path = Path(source).expanduser().resolve()
    try:
        raw_source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read manifest for migration: {exc}") from exc
    details = load_manifest_details(source_path, expand_env=False)
    canonical = details.manifest.model_dump(
        by_alias=True,
        exclude_none=True,
        mode="json",
    )
    changes: list[dict[str, str]] = []
    for path in _legacy_use_paths(raw_source):
        changes.append(
            {
                "path": path,
                "from": "use",
                "to": "uses",
                "reason": "Canonical provider reference field",
            }
        )
    old_api = canonical.get("apiVersion", "nodrix.dev/v1")
    canonical["apiVersion"] = "nodrix.dev/v2"
    if old_api != canonical["apiVersion"]:
        changes.append(
            {
                "path": "apiVersion",
                "from": str(old_api),
                "to": "nodrix.dev/v2",
                "reason": "Stable Manifest v2 contract",
            }
        )
    runtime = canonical.setdefault("runtime", {})
    if runtime.get("engine", "auto") == "auto":
        runtime["engine"] = "unified"
        changes.append(
            {
                "path": "runtime.engine",
                "from": "auto",
                "to": "unified",
                "reason": "Manifest v2 forbids an implicit executor choice",
            }
        )
    canonical.setdefault("fragments", {})
    canonical.setdefault("recording", {})
    canonical.setdefault("security", {})
    canonical.setdefault("placement", {})
    canonical.setdefault("resources", {})
    canonical.setdefault("applications", {})
    legacy_links = list(canonical.pop("links", []) or [])
    if legacy_links:
        edges = canonical.setdefault("edges", [])
        for index, link in enumerate(legacy_links):
            link_value = dict(link)
            uses = str(link_value.pop("uses"))
            parameters = dict(link_value.pop("parameters", {}) or {})
            edges.append(
                {
                    "from": link_value.pop("from"),
                    "to": link_value.pop("to"),
                    "transport": {
                        "uses": uses,
                        "parameters": parameters,
                    },
                }
            )
            changes.append(
                {
                    "path": f"links[{index}]",
                    "from": uses,
                    "to": f"edges[{len(edges) - 1}].transport.uses",
                    "reason": "External links are canonical Edge transports",
                }
            )
    canonical["links"] = []
    for name, node in dict(canonical.get("nodes") or {}).items():
        failure = dict(node.get("failure") or {})
        policy = failure.get("policy")
        replacement = {
            "restart": "restart_node",
            "disable_branch": "isolate_branch",
        }.get(policy)
        if replacement:
            failure["policy"] = replacement
            node["failure"] = failure
            changes.append(
                {
                    "path": f"nodes.{name}.failure.policy",
                    "from": str(policy),
                    "to": replacement,
                    "reason": "Stable 2.x failure-policy vocabulary",
                }
            )
    # Validation is performed before any destination or backup is written.
    validated = PipelineManifest.model_validate(deepcopy(canonical))
    return (
        validated.model_dump(by_alias=True, exclude_none=True, mode="json"),
        changes,
    )


def migrate_manifest(
    source: str | Path,
    *,
    output: str | Path | None = None,
    in_place: bool = False,
    write: bool = True,
) -> dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    if in_place and output is not None:
        raise ValueError("--in-place and --output are mutually exclusive")
    canonical, changes = prepare_v2_manifest(source_path)
    destination = (
        source_path
        if in_place
        else Path(output).expanduser().resolve()
        if output is not None
        else source_path.with_name(source_path.stem + ".v2" + source_path.suffix)
    )
    if not in_place and destination == source_path:
        raise ValueError("Migration output must differ from source unless --in-place is used")
    backup: Path | None = None
    rendered = yaml.safe_dump(canonical, sort_keys=False, allow_unicode=True)
    if write:
        if in_place:
            backup = _backup_path(source_path)
            shutil.copy2(source_path, backup)
        _write_atomic(destination, rendered)
    return {
        "schema": MIGRATION_SCHEMA,
        "source": str(source_path),
        "destination": str(destination),
        "backup": None if backup is None else str(backup),
        "written": write,
        "changes": changes,
        "incompatibilities": [],
        "manifest": canonical,
    }
