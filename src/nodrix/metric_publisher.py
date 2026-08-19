"""Backend-neutral publication capability for canonical typed Metrics.

MetricPublisher is the small capability exposed to Nodrix components.

It knows how to create canonical MetricRecord values, but deliberately knows
nothing about:

- Run IDs;
- RunMetricJournal;
- filesystem paths;
- legacy MetricsRecorder;
- Prometheus;
- process transport.

A runtime supplies a MetricSink.  Unit tests, local execution, process
isolation and future remote backends can therefore use the same component API
with different sink implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
from threading import Lock
from typing import (
    Callable,
    Mapping,
    Protocol,
    runtime_checkable,
)

from .model import (
    MetricDescriptor,
    MetricRecord,
    MetricValue,
    MetricValueType,
)


Clock = Callable[
    [],
    datetime,
]


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


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


@dataclass(
    frozen=True,
    slots=True,
)
class MetricPublishResult:
    """Result visible to the component after one publication attempt.

    ``accepted=False`` is an observability outcome, not an execution failure.
    For example, a bounded Run Metric sink may return ``record-limit``.

    Invalid Metric values are rejected before publication and therefore raise
    their normal validation exceptions instead of becoming a rejected result.
    """

    accepted: bool
    reason: str | None = None

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.accepted,
            bool,
        ):
            raise TypeError(
                "accepted must be a bool"
            )

        if self.accepted:
            if self.reason is not None:
                raise ValueError(
                    "accepted Metric publication "
                    "must not have a reason"
                )
            return

        if self.reason is None:
            raise ValueError(
                "rejected Metric publication "
                "requires a reason"
            )

        object.__setattr__(
            self,
            "reason",
            _required_text(
                self.reason,
                field_name=(
                    "Metric rejection reason"
                ),
            ),
        )


@runtime_checkable
class MetricSink(
    Protocol,
):
    """Backend-neutral receiver of one validated MetricRecord."""

    def publish(
        self,
        metric: MetricRecord,
    ) -> MetricPublishResult:
        ...


class NullMetricSink:
    """Default sink used when canonical Metric publication is disabled."""

    def publish(
        self,
        metric: MetricRecord,
    ) -> MetricPublishResult:
        if not isinstance(
            metric,
            MetricRecord,
        ):
            raise TypeError(
                "metric must be a MetricRecord"
            )

        return MetricPublishResult(
            accepted=False,
            reason="disabled",
        )


class BoundMetric:
    """Pre-bound MetricDescriptor optimized for repeated observations."""

    __slots__ = (
        "_descriptor",
        "_publisher",
    )

    def __init__(
        self,
        *,
        publisher: "MetricPublisher",
        descriptor: MetricDescriptor,
    ) -> None:
        if not isinstance(
            publisher,
            MetricPublisher,
        ):
            raise TypeError(
                "publisher must be a MetricPublisher"
            )

        if not isinstance(
            descriptor,
            MetricDescriptor,
        ):
            raise TypeError(
                "descriptor must be a MetricDescriptor"
            )

        self._publisher = publisher
        self._descriptor = descriptor

    @property
    def descriptor(
        self,
    ) -> MetricDescriptor:
        return self._descriptor

    @property
    def name(
        self,
    ) -> str:
        return self._descriptor.name

    @property
    def descriptor_id(
        self,
    ) -> str:
        return (
            self._descriptor
            .descriptor_id
        )

    def observe(
        self,
        value: MetricValue,
        *,
        observed_at: datetime | None = None,
        attributes: Mapping[
            str,
            str,
        ] | None = None,
    ) -> MetricPublishResult:
        """Publish one value using this prevalidated descriptor."""

        return self._publisher._observe_descriptor(
            self._descriptor,
            value,
            observed_at=observed_at,
            attributes=(
                {}
                if attributes is None
                else attributes
            ),
        )


class MetricPublisher:
    """Stable component-facing capability for typed Metric publication."""

    def __init__(
        self,
        *,
        source: str,
        sink: MetricSink | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self._source = _required_text(
            source,
            field_name="Metric source",
        )

        if sink is None:
            sink = NullMetricSink()

        if not isinstance(
            sink,
            MetricSink,
        ):
            raise TypeError(
                "sink must implement MetricSink"
            )

        if not callable(
            clock
        ):
            raise TypeError(
                "clock must be callable"
            )

        self._sink = sink
        self._clock = clock
        self._lock = Lock()
        self._bound: dict[
            tuple[
                str,
                str,
                str | None,
            ],
            BoundMetric,
        ] = {}

    @property
    def source(
        self,
    ) -> str:
        return self._source

    @property
    def enabled(
        self,
    ) -> bool:
        return not isinstance(
            self._sink,
            NullMetricSink,
        )

    def metric(
        self,
        name: str,
        *,
        value_type: MetricValueType | str,
        unit: str | None = None,
        description: str | None = None,
    ) -> BoundMetric:
        """Return a cached bound Metric for repeated hot-path observations."""

        descriptor = MetricDescriptor(
            name=name,
            value_type=value_type,
            unit=unit,
            description=description,
        )

        key = (
            descriptor.name,
            descriptor.value_type.value,
            descriptor.unit,
        )

        with self._lock:
            existing = self._bound.get(
                key
            )

            if existing is not None:
                return existing

            bound = BoundMetric(
                publisher=self,
                descriptor=descriptor,
            )

            self._bound[
                key
            ] = bound

            return bound

    def observe(
        self,
        name: str,
        value: MetricValue,
        *,
        value_type: MetricValueType | str,
        unit: str | None = None,
        description: str | None = None,
        observed_at: datetime | None = None,
        attributes: Mapping[
            str,
            str,
        ] | None = None,
    ) -> MetricPublishResult:
        """Convenience API for one-off Metric observations."""

        return self.metric(
            name,
            value_type=value_type,
            unit=unit,
            description=description,
        ).observe(
            value,
            observed_at=observed_at,
            attributes=attributes,
        )

    def _observe_descriptor(
        self,
        descriptor: MetricDescriptor,
        value: MetricValue,
        *,
        observed_at: datetime | None,
        attributes: Mapping[
            str,
            str,
        ],
    ) -> MetricPublishResult:
        timestamp = (
            self._clock()
            if observed_at is None
            else observed_at
        )

        metric = MetricRecord(
            descriptor=descriptor,
            value=value,
            observed_at=timestamp,
            source=self._source,
            attributes=attributes,
        )

        return self._publish_record(
            metric
        )

    def _publish_record(
        self,
        metric: MetricRecord,
    ) -> MetricPublishResult:
        """Publish one already validated executor-side MetricRecord."""

        if not isinstance(
            metric,
            MetricRecord,
        ):
            raise TypeError(
                "metric must be a MetricRecord"
            )

        if (
            metric.source
            != self._source
        ):
            raise ValueError(
                "Metric source does not match "
                f"publisher source {self._source!r}"
            )

        result = self._sink.publish(
            metric
        )

        if not isinstance(
            result,
            MetricPublishResult,
        ):
            raise TypeError(
                "MetricSink.publish() must return "
                "MetricPublishResult"
            )

        return result


__all__ = [
    "BoundMetric",
    "Clock",
    "MetricPublishResult",
    "MetricPublisher",
    "MetricSink",
    "NullMetricSink",
]
