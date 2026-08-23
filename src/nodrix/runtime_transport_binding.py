"""Backend-neutral runtime contracts for external transports.

These contracts describe already-resolved transport mechanics.

They do not know about SystemLink, PlannedLink, BackendContext,
PipelineManifest, providers, lifecycle, or orchestration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeTransportBinding:
    """One resolved external transport connection."""

    source: str
    target: str
    uses: str
    type_id: str | None = None
    parameters: Mapping[
        str,
        Any,
    ] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        for field_name in (
            "source",
            "target",
            "uses",
        ):
            value = getattr(
                self,
                field_name,
            )

            if (
                not isinstance(
                    value,
                    str,
                )
                or not value.strip()
            ):
                raise ValueError(
                    (
                        "RuntimeTransportBinding."
                        f"{field_name} must be "
                        "a non-empty string"
                    )
                )

        if (
            self.type_id is not None
            and (
                not isinstance(
                    self.type_id,
                    str,
                )
                or not self.type_id.strip()
            )
        ):
            raise ValueError(
                (
                    "RuntimeTransportBinding."
                    "type_id must be None "
                    "or a non-empty string"
                )
            )

        if not isinstance(
            self.parameters,
            Mapping,
        ):
            raise TypeError(
                (
                    "RuntimeTransportBinding."
                    "parameters must be a mapping"
                )
            )

        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(
                dict(
                    self.parameters
                )
            ),
        )


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeTransportSideBinding:
    """One backend-local side of an external transport."""

    transport: RuntimeTransportBinding
    direction: Literal[
        "inbound",
        "outbound",
    ]
    local_endpoint: str
    remote_endpoint: str

    def __post_init__(self) -> None:
        if not isinstance(
            self.transport,
            RuntimeTransportBinding,
        ):
            raise TypeError(
                (
                    "RuntimeTransportSideBinding."
                    "transport must be a "
                    "RuntimeTransportBinding"
                )
            )

        if self.direction not in {
            "inbound",
            "outbound",
        }:
            raise ValueError(
                (
                    "RuntimeTransportSideBinding."
                    "direction must be "
                    "'inbound' or 'outbound'"
                )
            )

        for field_name in (
            "local_endpoint",
            "remote_endpoint",
        ):
            value = getattr(
                self,
                field_name,
            )

            if (
                not isinstance(
                    value,
                    str,
                )
                or not value.strip()
            ):
                raise ValueError(
                    (
                        "RuntimeTransportSideBinding."
                        f"{field_name} must be "
                        "a non-empty string"
                    )
                )


__all__ = [
    "RuntimeTransportBinding",
    "RuntimeTransportSideBinding",
]
