"""Canonical foundation for user-defined Nodrix Definition kinds.

Concrete built-in domains keep their authoritative models:

- SystemModel
- Workflow
- Project
- legacy Pipeline
- Dataset / Artifact records

This module is only for user-defined Definition kinds such as:

    robot.firmware
    model.bundle
    mapping.map

A custom Definition uses one small canonical document shape:

    apiVersion: robot.firmware/v1
    kind: robot.firmware
    metadata:
      namespace: acme/rover-01
      name: navigation
    spec:
      ...

The document resolves to the same shared EntityRef / RevisionRef /
DefinitionRecord model used by built-in Nodrix domains.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .model import (
    DefinitionRecord,
    EntityRef,
    RevisionRef,
)


def _required_string(
    value: Any,
    *,
    field: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            f"{field} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field} must be non-empty"
        )

    return normalized


def _json_snapshot(
    value: Any,
    *,
    field: str,
) -> Any:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise TypeError(
            f"{field} must contain "
            "JSON-compatible values"
        ) from exc

    return json.loads(
        encoded
    )


def _custom_kind(
    value: Any,
) -> str:
    normalized = _required_string(
        value,
        field="custom definition kind",
    )

    if "." not in normalized:
        raise ValueError(
            "custom definition kind must be "
            "namespaced, for example "
            "'robot.firmware'"
        )

    return normalized


def normalize_custom_definition(
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one validated canonical custom Definition document."""

    if not isinstance(
        definition,
        Mapping,
    ):
        raise TypeError(
            "custom definition must be a mapping"
        )

    document = dict(
        definition
    )

    unknown = (
        set(document)
        - {
            "apiVersion",
            "kind",
            "metadata",
            "spec",
        }
    )

    if unknown:
        raise ValueError(
            "unknown custom definition field(s): "
            + ", ".join(
                sorted(
                    str(item)
                    for item in unknown
                )
            )
        )

    schema = _required_string(
        document.get(
            "apiVersion"
        ),
        field=(
            "custom definition apiVersion"
        ),
    )

    kind = _custom_kind(
        document.get("kind")
    )

    raw_metadata = document.get(
        "metadata"
    )

    if not isinstance(
        raw_metadata,
        Mapping,
    ):
        raise TypeError(
            "custom definition metadata "
            "must be a mapping"
        )

    metadata = _json_snapshot(
        dict(raw_metadata),
        field=(
            "custom definition metadata"
        ),
    )

    if not isinstance(
        metadata,
        dict,
    ):
        raise TypeError(
            "custom definition metadata "
            "must normalize to a mapping"
        )

    name = _required_string(
        metadata.get("name"),
        field=(
            "custom definition "
            "metadata.name"
        ),
    )

    namespace = _required_string(
        metadata.get("namespace"),
        field=(
            "custom definition "
            "metadata.namespace"
        ),
    )

    entity = EntityRef(
        kind=kind,
        namespace=namespace,
        name=name,
    )

    raw_spec = document.get(
        "spec",
        {},
    )

    if not isinstance(
        raw_spec,
        Mapping,
    ):
        raise TypeError(
            "custom definition spec "
            "must be a mapping"
        )

    spec = _json_snapshot(
        dict(raw_spec),
        field="custom definition spec",
    )

    if not isinstance(
        spec,
        dict,
    ):
        raise TypeError(
            "custom definition spec "
            "must normalize to a mapping"
        )

    metadata["namespace"] = (
        entity.namespace
    )

    metadata["name"] = (
        entity.name
    )

    return {
        "apiVersion": schema,
        "kind": entity.kind,
        "metadata": metadata,
        "spec": spec,
    }


def _custom_definition_digest(
    definition: Mapping[str, Any],
) -> str:
    encoded = json.dumps(
        definition,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def custom_definition_digest(
    definition: Mapping[str, Any],
) -> str:
    """Return semantic SHA-256 of one custom Definition."""

    normalized = (
        normalize_custom_definition(
            definition
        )
    )

    return _custom_definition_digest(
        normalized
    )


def custom_definition_entity_ref(
    definition: Mapping[str, Any],
) -> EntityRef:
    """Return logical identity declared by one custom Definition."""

    normalized = (
        normalize_custom_definition(
            definition
        )
    )

    metadata = normalized[
        "metadata"
    ]

    return EntityRef(
        kind=str(
            normalized["kind"]
        ),
        namespace=str(
            metadata["namespace"]
        ),
        name=str(
            metadata["name"]
        ),
    )


def custom_definition_record(
    definition: Mapping[str, Any],
    *,
    record_metadata: (
        Mapping[str, Any]
        | None
    ) = None,
) -> DefinitionRecord:
    """Wrap one custom Definition in the canonical object model."""

    normalized = (
        normalize_custom_definition(
            definition
        )
    )

    metadata = normalized[
        "metadata"
    ]

    entity = EntityRef(
        kind=str(
            normalized["kind"]
        ),
        namespace=str(
            metadata["namespace"]
        ),
        name=str(
            metadata["name"]
        ),
    )

    revision = (
        RevisionRef.from_sha256(
            entity,
            _custom_definition_digest(
                normalized
            ),
        )
    )

    if (
        record_metadata is not None
        and not isinstance(
            record_metadata,
            Mapping,
        )
    ):
        raise TypeError(
            "record_metadata must be "
            "a mapping or None"
        )

    return DefinitionRecord(
        entity=entity,
        revision=revision,
        schema=str(
            normalized[
                "apiVersion"
            ]
        ),
        definition=normalized,
        metadata=dict(
            record_metadata or {}
        ),
    )


__all__ = [
    "custom_definition_digest",
    "custom_definition_entity_ref",
    "custom_definition_record",
    "normalize_custom_definition",
]
