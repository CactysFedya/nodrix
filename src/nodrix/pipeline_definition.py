"""Canonical source-definition identity for legacy Nodrix Pipelines.

Pipeline is currently a compatibility/dataflow Definition whose loader may
resolve significantly more than the source file itself:

    source YAML
        -> compact normalization
        -> blocks / fragments
        -> profiles
        -> overrides
        -> environment expansion
        -> PipelineManifest

Existing Benchmark identity intentionally predates that resolved model and is
the SHA-256 of the exact Pipeline source file bytes.

This module preserves that policy explicitly.

It therefore models the *source Definition revision*, not a future resolved
Pipeline semantic revision.  The distinction is important:

    source revision != necessarily resolved Definition revision

Benchmark and existing Plan identities continue to use the source revision so
no historical identity policy changes in this release.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import yaml

from .branding import MANIFEST_API_V1
from .model import (
    DefinitionRecord,
    EntityRef,
    RevisionRef,
)


DEFAULT_PIPELINE_NAMESPACE = "workspace"


def _pipeline_path(
    value: str | Path,
) -> Path:
    path = (
        Path(value)
        .expanduser()
        .resolve()
    )

    if not path.exists():
        raise FileNotFoundError(
            f"Pipeline file does not exist: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"Pipeline path is not a file: {path}"
        )

    return path


def _pipeline_entity_ref(
    path: Path,
    *,
    namespace: str,
) -> EntityRef:
    return EntityRef(
        kind="pipeline",
        namespace=namespace,
        name=path.stem,
    )


def _pipeline_source_digest(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(
                chunk
            )

    return digest.hexdigest()


def pipeline_source_digest(
    value: str | Path,
) -> str:
    """Return SHA-256 of the exact Pipeline source file bytes."""

    return _pipeline_source_digest(
        _pipeline_path(value)
    )


def pipeline_entity_ref(
    value: str | Path,
    *,
    namespace: str = (
        DEFAULT_PIPELINE_NAMESPACE
    ),
) -> EntityRef:
    """Return legacy-compatible logical Pipeline identity.

    The filename stem intentionally remains the identity name because existing
    Benchmark operations already use this policy.
    """

    return _pipeline_entity_ref(
        _pipeline_path(value),
        namespace=namespace,
    )


def pipeline_source_revision_ref(
    value: str | Path,
    *,
    namespace: str = (
        DEFAULT_PIPELINE_NAMESPACE
    ),
) -> RevisionRef:
    """Return one exact source-file revision of a Pipeline."""

    path = _pipeline_path(
        value
    )

    entity = _pipeline_entity_ref(
        path,
        namespace=namespace,
    )

    return RevisionRef.from_sha256(
        entity,
        _pipeline_source_digest(
            path
        ),
    )


def pipeline_source_identity(
    value: str | Path,
    *,
    namespace: str = (
        DEFAULT_PIPELINE_NAMESPACE
    ),
) -> tuple[
    EntityRef,
    RevisionRef,
]:
    """Return logical Pipeline identity and exact source revision."""

    path = _pipeline_path(
        value
    )

    entity = _pipeline_entity_ref(
        path,
        namespace=namespace,
    )

    revision = RevisionRef.from_sha256(
        entity,
        _pipeline_source_digest(
            path
        ),
    )

    return entity, revision


def pipeline_source_definition_record(
    value: str | Path,
    *,
    namespace: str = (
        DEFAULT_PIPELINE_NAMESPACE
    ),
    metadata: (
        Mapping[str, Any]
        | None
    ) = None,
) -> DefinitionRecord:
    """Wrap exact Pipeline source bytes in a canonical DefinitionRecord.

    This function deliberately does not call ``load_manifest_details``.
    Resolving blocks, fragments, profiles, overrides, or environment variables
    would create a different semantic object from the source revision used by
    existing Benchmark identities.
    """

    path = _pipeline_path(
        value
    )

    source = path.read_bytes()

    try:
        document = yaml.safe_load(
            source.decode("utf-8")
        )
    except (
        UnicodeDecodeError,
        yaml.YAMLError,
    ) as exc:
        raise ValueError(
            f"Cannot read Pipeline source definition: {path}"
        ) from exc

    if not isinstance(
        document,
        dict,
    ):
        raise ValueError(
            "Pipeline source definition "
            "must contain a YAML mapping"
        )

    raw_schema = document.get(
        "apiVersion",
        MANIFEST_API_V1,
    )

    if not isinstance(
        raw_schema,
        str,
    ) or not raw_schema.strip():
        raise ValueError(
            "Pipeline source definition "
            "must use a non-empty apiVersion"
        )

    entity = _pipeline_entity_ref(
        path,
        namespace=namespace,
    )

    revision = RevisionRef.from_sha256(
        entity,
        hashlib.sha256(
            source
        ).hexdigest(),
    )

    record_metadata: dict[
        str,
        Any,
    ] = {
        "source_path": str(
            path
        ),
        "source_revision": True,
    }

    if metadata is not None:
        if not isinstance(
            metadata,
            Mapping,
        ):
            raise TypeError(
                "pipeline definition metadata "
                "must be a mapping or None"
            )

        record_metadata.update(
            metadata
        )

    return DefinitionRecord(
        entity=entity,
        revision=revision,
        schema=raw_schema.strip(),
        # Exact bytes are retained because this revision intentionally
        # identifies the physical source representation, including formatting.
        definition=source,
        metadata=record_metadata,
    )


__all__ = [
    "DEFAULT_PIPELINE_NAMESPACE",
    "pipeline_entity_ref",
    "pipeline_source_definition_record",
    "pipeline_source_digest",
    "pipeline_source_identity",
    "pipeline_source_revision_ref",
]
