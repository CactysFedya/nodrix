"""Canonical typed Metric records shared across Nodrix domains.

Metrics are measurements.

They are deliberately distinct from:

- lifecycle Events;
- diagnostic Logs;
- persisted Artifacts;
- legacy process/runtime telemetry snapshots.

This module contains no Run identity, filesystem storage, Prometheus
representation, recorder thread or backend-specific behavior.

Run-bound persistence is an outer layer.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Mapping


METRIC_DESCRIPTOR_IDENTITY_SCHEMA = (
    "nodrix.metric-descriptor-identity/v1"
)


class MetricValueType(
    str,
    Enum,
):
    """Canonical scalar value type of one Metric."""

    INTEGER = "integer"
    FLOAT = "float"

    def __str__(
        self,
    ) -> str:
        return self.value

    @classmethod
    def parse(
        cls,
        value: str | "MetricValueType",
    ) -> "MetricValueType":
        if isinstance(
            value,
            cls,
        ):
            return value

        if not isinstance(
            value,
            str,
        ):
            raise TypeError(
                "metric value type must be a string"
            )

        normalized = (
            value.strip().lower()
        )

        if not normalized:
            raise ValueError(
                "metric value type must be non-empty"
            )

        try:
            return cls(
                normalized
            )
        except ValueError as exc:
            allowed = ", ".join(
                item.value
                for item in cls
            )

            raise ValueError(
                "unsupported metric value type "
                f"{value!r}; expected one of: "
                f"{allowed}"
            ) from exc


def _required_text(
    value: str,
    *,
    field_name: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            f"{field_name} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} must be non-empty"
        )

    return normalized


def _optional_text(
    value: str | None,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    return _required_text(
        value,
        field_name=field_name,
    )


def _metric_name(
    value: str,
) -> str:
    normalized = _required_text(
        value,
        field_name="metric name",
    )

    if any(
        character.isspace()
        for character in normalized
    ):
        raise ValueError(
            "metric name must not contain whitespace"
        )

    if "\x00" in normalized:
        raise ValueError(
            "metric name contains an unsupported character"
        )

    return normalized


def canonical_metric_descriptor_id(
    *,
    name: str,
    value_type: MetricValueType | str,
    unit: str | None,
) -> str:
    """Return deterministic identity of one Metric semantic contract."""

    canonical_name = _metric_name(
        name
    )

    canonical_type = (
        MetricValueType.parse(
            value_type
        )
    )

    canonical_unit = _optional_text(
        unit,
        field_name="metric unit",
    )

    document = {
        "schema": (
            METRIC_DESCRIPTOR_IDENTITY_SCHEMA
        ),
        "name": canonical_name,
        "valueType": (
            canonical_type.value
        ),
        "unit": canonical_unit,
    }

    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode(
        "utf-8"
    )

    return (
        "metric-"
        + sha256(
            encoded
        ).hexdigest()
    )


@dataclass(
    frozen=True,
    slots=True,
)
class MetricDescriptor:
    """Immutable semantic description of one typed measurement.

    ``description`` is documentation and deliberately does not participate in
    descriptor identity.

    ``name``, ``value_type`` and ``unit`` define measurement semantics and
    therefore determine ``descriptor_id``.
    """

    name: str
    value_type: MetricValueType | str
    unit: str | None = None
    description: str | None = None

    def __post_init__(
        self,
    ) -> None:
        name = _metric_name(
            self.name
        )

        value_type = (
            MetricValueType.parse(
                self.value_type
            )
        )

        unit = _optional_text(
            self.unit,
            field_name="metric unit",
        )

        description = _optional_text(
            self.description,
            field_name="metric description",
        )

        object.__setattr__(
            self,
            "name",
            name,
        )

        object.__setattr__(
            self,
            "value_type",
            value_type,
        )

        object.__setattr__(
            self,
            "unit",
            unit,
        )

        object.__setattr__(
            self,
            "description",
            description,
        )

    @property
    def descriptor_id(
        self,
    ) -> str:
        return canonical_metric_descriptor_id(
            name=self.name,
            value_type=self.value_type,
            unit=self.unit,
        )


MetricValue = int | float


def _metric_value(
    descriptor: MetricDescriptor,
    value: MetricValue,
) -> MetricValue:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            (
                int,
                float,
            ),
        )
    ):
        raise TypeError(
            "metric value must be an int or float, "
            "not bool or arbitrary JSON"
        )

    if (
        descriptor.value_type
        is MetricValueType.INTEGER
    ):
        if not isinstance(
            value,
            int,
        ):
            raise TypeError(
                "integer metric requires an int value"
            )

        return value

    numeric = float(
        value
    )

    if not math.isfinite(
        numeric
    ):
        raise ValueError(
            "float metric value must be finite"
        )

    return numeric


def _attributes(
    value: Mapping[str, str],
) -> Mapping[str, str]:
    if not isinstance(
        value,
        Mapping,
    ):
        raise TypeError(
            "metric attributes must be a mapping"
        )

    result: dict[
        str,
        str,
    ] = {}

    for raw_key, raw_value in (
        value.items()
    ):
        key = _required_text(
            raw_key,
            field_name=(
                "metric attribute key"
            ),
        )

        if not isinstance(
            raw_value,
            str,
        ):
            raise TypeError(
                "metric attribute values "
                "must be strings"
            )

        item = raw_value.strip()

        if not item:
            raise ValueError(
                "metric attribute values "
                "must be non-empty"
            )

        result[
            key
        ] = item

    return MappingProxyType(
        dict(
            sorted(
                result.items()
            )
        )
    )


@dataclass(
    frozen=True,
    slots=True,
)
class MetricRecord:
    """One immutable typed measurement observation.

    The record is deliberately Run-neutral.

    Run identity, append sequence and storage-loss accounting belong to the
    persistent Run metric envelope introduced by the Run observability layer.
    """

    descriptor: MetricDescriptor
    value: MetricValue
    observed_at: datetime
    source: str | None = None
    attributes: Mapping[str, str] = field(
        default_factory=dict
    )

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.descriptor,
            MetricDescriptor,
        ):
            raise TypeError(
                "descriptor must be a MetricDescriptor"
            )

        if not isinstance(
            self.observed_at,
            datetime,
        ):
            raise TypeError(
                "observed_at must be a datetime"
            )

        if (
            self.observed_at.tzinfo
            is None
            or self.observed_at.utcoffset()
            is None
        ):
            raise ValueError(
                "observed_at must be timezone-aware"
            )

        source = _optional_text(
            self.source,
            field_name="metric source",
        )

        value = _metric_value(
            self.descriptor,
            self.value,
        )

        attributes = _attributes(
            self.attributes
        )

        object.__setattr__(
            self,
            "source",
            source,
        )

        object.__setattr__(
            self,
            "value",
            value,
        )

        object.__setattr__(
            self,
            "attributes",
            attributes,
        )

    @property
    def name(
        self,
    ) -> str:
        return self.descriptor.name

    @property
    def descriptor_id(
        self,
    ) -> str:
        return self.descriptor.descriptor_id

    @property
    def value_type(
        self,
    ) -> MetricValueType:
        return self.descriptor.value_type

    @property
    def unit(
        self,
    ) -> str | None:
        return self.descriptor.unit


__all__ = [
    "METRIC_DESCRIPTOR_IDENTITY_SCHEMA",
    "MetricDescriptor",
    "MetricRecord",
    "MetricValue",
    "MetricValueType",
    "canonical_metric_descriptor_id",
]
