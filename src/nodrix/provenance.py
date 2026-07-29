from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
from typing import Any

from .benchmarking import model_inventory
from .device import device_doctor
from .manifest import PipelineManifest
from .packages import resolve_package_node
from .resources import system_snapshot


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_implementation(reference: str, base_dir: Path) -> Path | None:
    if reference.startswith("native:"):
        value = reference.removeprefix("native:").split("#", 1)[0]
    elif ":" in reference:
        value = reference.rsplit(":", 1)[0]
        if not (value.endswith(".py") or "/" in value or "\\" in value):
            return None
    else:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path if path.is_file() else None


def plugin_inventory(
    manifest: PipelineManifest,
    base_dir: Path,
    description: dict[str, Any],
) -> list[dict[str, Any]]:
    described = dict(description.get("nodes") or {})
    result: list[dict[str, Any]] = []
    for name, config in manifest.nodes.items():
        reference = resolve_package_node(config.uses)
        item: dict[str, Any] = {
            "node": name,
            "uses": config.uses,
            "resolved_uses": reference,
            "implementation": dict(described.get(name) or {}).get(
                "implementation",
                "native" if reference.startswith("native:") else "python",
            ),
            "class": dict(described.get(name) or {}).get("class"),
        }
        path = _local_implementation(reference, base_dir)
        if path is not None:
            item.update(
                {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        result.append(item)
    return result


def hardware_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "system": system_snapshot(),
    }
    try:
        result["devices"] = device_doctor()
    except Exception as exc:
        result["devices"] = {
            "available": False,
            "diagnostic_error": f"{type(exc).__name__}: {exc}",
        }
    return result


def write_run_provenance(
    run_dir: Path,
    manifest: PipelineManifest,
    manifest_path: Path,
    description: dict[str, Any],
) -> None:
    artifacts = {
        "hardware.json": hardware_snapshot(),
        "plugins.json": {
            "plugins": plugin_inventory(
                manifest,
                manifest_path.parent,
                description,
            )
        },
        "models.json": {
            "models": model_inventory(manifest_path),
        },
    }
    for name, value in artifacts.items():
        (run_dir / name).write_text(
            json.dumps(
                value,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
