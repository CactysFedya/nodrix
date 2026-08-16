"""Canonical identity bridge for a Nodrix project definition.

A Project is a logical execution context for engineering operations such as
build and test.

Its canonical revision represents the declarative project definition stored in
``nodrix.yaml``.

Source files and materialized inputs are intentionally not folded into this
definition revision; they belong to provenance/data relations.

The Project Definition uses the same canonical identity primitives as other
Nodrix domains:

    project document
        -> EntityRef
        -> RevisionRef
        -> DefinitionRecord
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import yaml

from .model import (
    DefinitionRecord,
    EntityRef,
    RevisionRef,
)
from .workspace import (
    PROJECT_FILE,
    find_workspace,
)


DEFAULT_PROJECT_NAMESPACE = "workspace"


def project_root(
    value: str | Path | None = None,
) -> Path:
    selected = (
        Path(value or Path.cwd())
        .expanduser()
        .resolve()
    )

    root = find_workspace(
        selected
    )

    if root is not None:
        return root

    if (
        selected / PROJECT_FILE
    ).is_file():
        return selected

    raise LookupError(
        f"No {PROJECT_FILE} found from "
        f"{selected}"
    )


def project_document(
    value: str | Path | None = None,
) -> dict[str, object]:
    root = project_root(
        value
    )

    path = (
        root / PROJECT_FILE
    )

    raw = yaml.safe_load(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(
        raw,
        dict,
    ):
        raise ValueError(
            f"{path} must contain "
            "a YAML mapping"
        )

    return dict(raw)


def _project_entity_ref(
    document: Mapping[str, object],
    *,
    namespace: str,
) -> EntityRef:
    name = str(
        document.get("name") or ""
    ).strip()

    if not name:
        raise ValueError(
            f"{PROJECT_FILE} must declare "
            "project name"
        )

    return EntityRef(
        kind="project",
        namespace=namespace,
        name=name,
    )


def project_entity_ref(
    value: str | Path | None = None,
    *,
    namespace: str = (
        DEFAULT_PROJECT_NAMESPACE
    ),
) -> EntityRef:
    document = project_document(
        value
    )

    return _project_entity_ref(
        document,
        namespace=namespace,
    )


def _project_definition_digest(
    document: Mapping[str, object],
) -> str:
    """Hash one already-loaded Project document.

    The serialization intentionally preserves the exact semantic digest policy
    previously used by ``project_definition_digest``.
    """

    normalized = yaml.safe_dump(
        dict(document),
        sort_keys=True,
        allow_unicode=True,
    ).encode("utf-8")

    return hashlib.sha256(
        normalized
    ).hexdigest()


def project_definition_digest(
    value: str | Path | None = None,
) -> str:
    """Return semantic SHA-256 of the declarative Project Definition."""

    return _project_definition_digest(
        project_document(value)
    )


def project_revision_ref(
    value: str | Path | None = None,
    *,
    namespace: str = (
        DEFAULT_PROJECT_NAMESPACE
    ),
) -> RevisionRef:
    """Return one immutable revision of the canonical Project entity."""

    document = project_document(
        value
    )

    entity = _project_entity_ref(
        document,
        namespace=namespace,
    )

    return RevisionRef.from_sha256(
        entity,
        _project_definition_digest(
            document
        ),
    )


def project_definition_record(
    value: str | Path | None = None,
    *,
    namespace: str = (
        DEFAULT_PROJECT_NAMESPACE
    ),
    metadata: (
        Mapping[str, Any]
        | None
    ) = None,
) -> DefinitionRecord:
    """Load one Project as a canonical DefinitionRecord.

    Filesystem location is explanatory metadata only and does not contribute
    to Project identity or revision.
    """

    root = project_root(
        value
    )

    document = project_document(
        root
    )

    raw_schema = document.get(
        "schema"
    )

    if not isinstance(
        raw_schema,
        str,
    ) or not raw_schema.strip():
        raise ValueError(
            f"{PROJECT_FILE} must declare "
            "a non-empty project schema"
        )

    entity = _project_entity_ref(
        document,
        namespace=namespace,
    )

    revision = (
        RevisionRef.from_sha256(
            entity,
            _project_definition_digest(
                document
            ),
        )
    )

    definition_metadata: dict[
        str,
        Any,
    ] = {
        "source_path": str(
            (
                root
                / PROJECT_FILE
            ).resolve()
        ),
    }

    if metadata is not None:
        if not isinstance(
            metadata,
            Mapping,
        ):
            raise TypeError(
                "project definition metadata "
                "must be a mapping or None"
            )

        definition_metadata.update(
            metadata
        )

    return DefinitionRecord(
        entity=entity,
        revision=revision,
        schema=raw_schema.strip(),
        definition=document,
        metadata=(
            definition_metadata
        ),
    )


__all__ = [
    "DEFAULT_PROJECT_NAMESPACE",
    "project_definition_digest",
    "project_definition_record",
    "project_document",
    "project_entity_ref",
    "project_revision_ref",
    "project_root",
]
