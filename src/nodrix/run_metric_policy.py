"""Bounded storage policy for canonical Run Metrics.

This policy belongs to Run / Execution observability, not to System Definition.

It deliberately does not alter Plan semantics and does not participate in Plan
identity.

Binding this policy into higher-level ExecutionPolicy/profile authoring is
handled by a later observability layer.  This module only defines the canonical
Metric storage limits.
"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_METRIC_MAX_RECORDS = 100_000
DEFAULT_METRIC_MAX_BYTES = 4 * 1024 * 1024
DEFAULT_METRIC_MAX_RECORD_BYTES = 64 * 1024


def _positive_int(
    value: int,
    *,
    field_name: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
    ):
        raise TypeError(
            f"{field_name} must be an integer"
        )

    if value < 1:
        raise ValueError(
            f"{field_name} must be positive"
        )

    return value


@dataclass(
    frozen=True,
    slots=True,
)
class RunMetricPolicy:
    """Canonical bounded-storage policy for Run Metrics.

    ``overflow="drop"`` means Metric loss is allowed only when it is explicitly
    accounted for.  Metrics never control execution success/failure merely
    because the observability storage budget was exhausted.
    """

    max_records: int = (
        DEFAULT_METRIC_MAX_RECORDS
    )
    max_bytes: int = (
        DEFAULT_METRIC_MAX_BYTES
    )
    max_record_bytes: int = (
        DEFAULT_METRIC_MAX_RECORD_BYTES
    )
    overflow: str = "drop"

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "max_records",
            _positive_int(
                self.max_records,
                field_name="max_records",
            ),
        )

        object.__setattr__(
            self,
            "max_bytes",
            _positive_int(
                self.max_bytes,
                field_name="max_bytes",
            ),
        )

        object.__setattr__(
            self,
            "max_record_bytes",
            _positive_int(
                self.max_record_bytes,
                field_name="max_record_bytes",
            ),
        )

        if not isinstance(
            self.overflow,
            str,
        ):
            raise TypeError(
                "overflow must be a string"
            )

        overflow = (
            self.overflow
            .strip()
            .lower()
        )

        if overflow != "drop":
            raise ValueError(
                "unsupported Metric overflow policy; "
                "expected 'drop'"
            )

        object.__setattr__(
            self,
            "overflow",
            overflow,
        )


__all__ = [
    "DEFAULT_METRIC_MAX_BYTES",
    "DEFAULT_METRIC_MAX_RECORD_BYTES",
    "DEFAULT_METRIC_MAX_RECORDS",
    "RunMetricPolicy",
]
