"""Canonical identity bridge for a Nodrix project definition.

A project is a logical execution context for engineering operations such as
build and test.  Its canonical revision represents the declarative project
definition stored in nodrix.yaml.

Source files and materialized inputs are intentionally not folded into this
definition revision; they belong to provenance/data relations.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from .model import EntityRef, RevisionRef
from .workspace import PROJECT_FILE, find_workspace


DEFAULT_PROJECT_NAMESPACE = "workspace"


def project_root(
    value: str | Path | None = None,
) -> Path:
    selected = Path(value or Path.cwd()).expanduser().resolve()

    root = find_workspace(selected)
    if root is not None:
        return root

    if (selected / PROJECT_FILE).is_file():
        return selected

    raise LookupError(
        f"No {PROJECT_FILE} found from {selected}"
    )


def project_document(
    value: str | Path | None = None,
) -> dict[str, object]:
    root = project_root(value)
    path = root / PROJECT_FILE

    raw = yaml.safe_load(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(raw, dict):
        raise ValueError(
            f"{path} must contain a YAML mapping"
        )

    return dict(raw)


def project_entity_ref(
    value: str | Path | None = None,
    *,
    namespace: str = DEFAULT_PROJECT_NAMESPACE,
) -> EntityRef:
    document = project_document(value)

    name = str(document.get("name") or "").strip()
    if not name:
        raise ValueError(
            f"{PROJECT_FILE} must declare project name"
        )

    return EntityRef(
        kind="project",
        namespace=namespace,
        name=name,
    )


def project_definition_digest(
    value: str | Path | None = None,
) -> str:
    """Return semantic SHA-256 of the declarative project definition."""

    document = project_document(value)

    normalized = yaml.safe_dump(
        document,
        sort_keys=True,
        allow_unicode=True,
    ).encode("utf-8")

    return hashlib.sha256(normalized).hexdigest()


def project_revision_ref(
    value: str | Path | None = None,
    *,
    namespace: str = DEFAULT_PROJECT_NAMESPACE,
) -> RevisionRef:
    entity = project_entity_ref(
        value,
        namespace=namespace,
    )

    return RevisionRef.from_sha256(
        entity,
        project_definition_digest(value),
    )


__all__ = [
    "DEFAULT_PROJECT_NAMESPACE",
    "project_definition_digest",
    "project_document",
    "project_entity_ref",
    "project_revision_ref",
    "project_root",
]
