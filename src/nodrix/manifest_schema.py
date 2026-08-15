"""JSON Schema generation for canonical Plyctl pipeline manifests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .manifest import PipelineManifest


MANIFEST_SCHEMA_ID = "https://plyctl.dev/schemas/pipeline-2.2.json"


def manifest_json_schema() -> dict[str, Any]:
    schema = PipelineManifest.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = MANIFEST_SCHEMA_ID
    schema["title"] = "Plyctl Pipeline Manifest"
    schema["description"] = (
        "Canonical Plyctl 2.x pipeline manifest. The deprecated 'use' alias "
        "is accepted by the compatibility parser but intentionally omitted "
        "from this schema. Legacy nodrix.dev API versions remain accepted "
        "throughout the 2.x series."
    )
    return schema


def render_manifest_schema() -> str:
    return json.dumps(
        manifest_json_schema(),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    ) + "\n"


def write_manifest_schema(path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(render_manifest_schema())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            Path(temporary).unlink()
        except OSError:
            pass
        raise
    return target


__all__ = [
    "MANIFEST_SCHEMA_ID",
    "manifest_json_schema",
    "render_manifest_schema",
    "write_manifest_schema",
]
