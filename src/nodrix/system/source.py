"""Authoring boundary for Nodrix System sources.

A System Source is the human-facing representation used during authoring.
It may eventually use System Modules through ``imports`` and semantic
configuration through ``config``.

Those authoring mechanisms are resolved before SystemModel validation and
therefore never become canonical SystemModel fields.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..errors import NodrixError


_AUTHORING_FIELDS = frozenset({
    "imports",
    "config",
})


class SystemSourceError(NodrixError):
    """A human-facing System Source cannot be resolved."""


@dataclass(frozen=True, slots=True)
class SystemSourceResolution:
    """Result of resolving one System authoring source."""

    document: Any
    source: Path | None
    sources: tuple[Path, ...]


def resolve_system_source_document(
    raw: Any,
    *,
    source: str | Path | None = None,
) -> SystemSourceResolution:
    """Resolve authoring syntax before canonical System validation.

    Alpha 1 establishes the resolution boundary only. Existing canonical
    ``nodrix.system/v1`` documents pass through unchanged.

    ``imports`` and ``config`` are reserved for later 2.17 milestones so they
    cannot accidentally leak into SystemModel as canonical fields.
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

    authoring_fields = sorted(
        _AUTHORING_FIELDS.intersection(raw)
    )

    if authoring_fields:
        rendered = ", ".join(authoring_fields)
        raise SystemSourceError(
            "System authoring fields are reserved but not enabled yet: "
            f"{rendered}"
        )

    return SystemSourceResolution(
        document=deepcopy(dict(raw)),
        source=source_path,
        sources=(
            (source_path,)
            if source_path is not None
            else ()
        ),
    )


__all__ = [
    "SystemSourceError",
    "SystemSourceResolution",
    "resolve_system_source_document",
]
