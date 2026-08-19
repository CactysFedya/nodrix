"""Strict transport representation for canonical Metric publication.

This is an execution transport contract, not persistent Run history.

    MetricRecord
        -> MetricPublication
        -> executor transport
        -> MetricRecord

Run identity, sequence numbers and durable storage are deliberately absent.
"""

from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from typing import (
    Any,
    Mapping,
)

from .metric_publisher import (
    MetricPublishResult,
)
from .model import (
    MetricDescriptor,
    MetricRecord,
)


METRIC_PUBLICATION_API_VERSION = (
    "nodrix.metric-publication/v1"
)
METRIC_PUBLICATION_KIND = (
    "MetricPublication"
)

METRIC_PUBLICATION_RESULT_API_VERSION = (
    "nodrix.metric-publication-result/v1"
)
METRIC_PUBLICATION_RESULT_KIND = (
    "MetricPublicationResult"
)


def _exact_fields(
    document: Mapping[str, Any],
    *,
    expected: set[str],
    label: str,
) -> None:
    actual = set(
        document
    )

    if actual != expected:
        raise ValueError(
            f"{label} has invalid fields; "
            f"missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _timestamp_text(
    value: datetime,
) -> str:
    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError(
            "Metric timestamp must be a datetime"
        )

    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            "Metric timestamp must be timezone-aware"
        )

    return (
        value.astimezone(
            timezone.utc
        )
        .isoformat(
            timespec="microseconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


def _timestamp_from_text(
    value: object,
) -> datetime:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            "Metric timestamp must be a string"
        )

    text = value.strip()

    if not text:
        raise ValueError(
            "Metric timestamp must be non-empty"
        )

    try:
        parsed = datetime.fromisoformat(
            (
                text[:-1]
                + "+00:00"
                if text.endswith("Z")
                else text
            )
        )
    except ValueError as exc:
        raise ValueError(
            "Metric timestamp must be ISO-8601"
        ) from exc

    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise ValueError(
            "Metric timestamp must be timezone-aware"
        )

    return parsed.astimezone(
        timezone.utc
    )


def metric_publication_document(
    metric: MetricRecord,
) -> dict[str, Any]:
    """Serialize one canonical MetricRecord for executor transport."""

    if not isinstance(
        metric,
        MetricRecord,
    ):
        raise TypeError(
            "metric must be a MetricRecord"
        )

    descriptor = (
        metric.descriptor
    )

    return {
        "apiVersion": (
            METRIC_PUBLICATION_API_VERSION
        ),
        "kind": (
            METRIC_PUBLICATION_KIND
        ),
        "metric": {
            "descriptor": {
                "descriptorId": (
                    descriptor.descriptor_id
                ),
                "name": descriptor.name,
                "valueType": (
                    descriptor.value_type.value
                ),
                "unit": descriptor.unit,
                "description": (
                    descriptor.description
                ),
            },
            "value": metric.value,
            "observedAt": (
                _timestamp_text(
                    metric.observed_at
                )
            ),
            "source": metric.source,
            "attributes": dict(
                metric.attributes
            ),
        },
    }


def metric_from_publication_document(
    value: object,
) -> MetricRecord:
    """Strictly validate one MetricPublication transport document."""

    if not isinstance(
        value,
        Mapping,
    ):
        raise TypeError(
            "MetricPublication must be a mapping"
        )

    publication = dict(
        value
    )

    _exact_fields(
        publication,
        expected={
            "apiVersion",
            "kind",
            "metric",
        },
        label="MetricPublication",
    )

    if (
        publication[
            "apiVersion"
        ]
        != METRIC_PUBLICATION_API_VERSION
    ):
        raise ValueError(
            "unsupported MetricPublication apiVersion"
        )

    if (
        publication[
            "kind"
        ]
        != METRIC_PUBLICATION_KIND
    ):
        raise ValueError(
            "invalid MetricPublication kind"
        )

    raw_metric = publication[
        "metric"
    ]

    if not isinstance(
        raw_metric,
        Mapping,
    ):
        raise TypeError(
            "MetricPublication.metric "
            "must be a mapping"
        )

    metric = dict(
        raw_metric
    )

    _exact_fields(
        metric,
        expected={
            "descriptor",
            "value",
            "observedAt",
            "source",
            "attributes",
        },
        label="MetricPublication.metric",
    )

    raw_descriptor = metric[
        "descriptor"
    ]

    if not isinstance(
        raw_descriptor,
        Mapping,
    ):
        raise TypeError(
            "Metric descriptor must be a mapping"
        )

    descriptor_document = dict(
        raw_descriptor
    )

    _exact_fields(
        descriptor_document,
        expected={
            "descriptorId",
            "name",
            "valueType",
            "unit",
            "description",
        },
        label="Metric descriptor",
    )

    descriptor = MetricDescriptor(
        name=descriptor_document[
            "name"
        ],
        value_type=descriptor_document[
            "valueType"
        ],
        unit=descriptor_document[
            "unit"
        ],
        description=descriptor_document[
            "description"
        ],
    )

    descriptor_id = (
        descriptor_document[
            "descriptorId"
        ]
    )

    if not isinstance(
        descriptor_id,
        str,
    ):
        raise TypeError(
            "Metric descriptorId must be a string"
        )

    if (
        descriptor_id
        != descriptor.descriptor_id
    ):
        raise ValueError(
            "Metric descriptorId does not match "
            "canonical descriptor identity"
        )

    source = metric[
        "source"
    ]

    if (
        source is not None
        and not isinstance(
            source,
            str,
        )
    ):
        raise TypeError(
            "Metric source must be a string or null"
        )

    attributes = metric[
        "attributes"
    ]

    if not isinstance(
        attributes,
        Mapping,
    ):
        raise TypeError(
            "Metric attributes must be a mapping"
        )

    return MetricRecord(
        descriptor=descriptor,
        value=metric[
            "value"
        ],
        observed_at=_timestamp_from_text(
            metric[
                "observedAt"
            ]
        ),
        source=source,
        attributes=dict(
            attributes
        ),
    )


def metric_publication_result_document(
    result: MetricPublishResult | None = None,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    """Serialize successful publication outcome or transport failure."""

    if (
        result is None
        and error is None
    ):
        raise ValueError(
            "Metric publication result requires "
            "either result or error"
        )

    if (
        result is not None
        and error is not None
    ):
        raise ValueError(
            "Metric publication result cannot contain "
            "both result and error"
        )

    if error is not None:
        if not isinstance(
            error,
            str,
        ):
            raise TypeError(
                "Metric publication error must be a string"
            )

        normalized = (
            error.strip()
        )

        if not normalized:
            raise ValueError(
                "Metric publication error must be non-empty"
            )

        return {
            "apiVersion": (
                METRIC_PUBLICATION_RESULT_API_VERSION
            ),
            "kind": (
                METRIC_PUBLICATION_RESULT_KIND
            ),
            "ok": False,
            "accepted": None,
            "reason": None,
            "error": normalized,
        }

    if not isinstance(
        result,
        MetricPublishResult,
    ):
        raise TypeError(
            "result must be a MetricPublishResult"
        )

    return {
        "apiVersion": (
            METRIC_PUBLICATION_RESULT_API_VERSION
        ),
        "kind": (
            METRIC_PUBLICATION_RESULT_KIND
        ),
        "ok": True,
        "accepted": result.accepted,
        "reason": result.reason,
        "error": None,
    }


def metric_publish_result_from_document(
    value: object,
) -> MetricPublishResult:
    """Decode one executor response to a Metric publication."""

    if not isinstance(
        value,
        Mapping,
    ):
        raise TypeError(
            "MetricPublicationResult must be a mapping"
        )

    document = dict(
        value
    )

    _exact_fields(
        document,
        expected={
            "apiVersion",
            "kind",
            "ok",
            "accepted",
            "reason",
            "error",
        },
        label="MetricPublicationResult",
    )

    if (
        document[
            "apiVersion"
        ]
        != METRIC_PUBLICATION_RESULT_API_VERSION
    ):
        raise ValueError(
            "unsupported MetricPublicationResult apiVersion"
        )

    if (
        document[
            "kind"
        ]
        != METRIC_PUBLICATION_RESULT_KIND
    ):
        raise ValueError(
            "invalid MetricPublicationResult kind"
        )

    ok = document[
        "ok"
    ]

    if not isinstance(
        ok,
        bool,
    ):
        raise TypeError(
            "MetricPublicationResult.ok must be a bool"
        )

    if not ok:
        if (
            document[
                "accepted"
            ]
            is not None
            or document[
                "reason"
            ]
            is not None
        ):
            raise ValueError(
                "failed MetricPublicationResult "
                "cannot contain publication outcome"
            )

        error = document[
            "error"
        ]

        if (
            not isinstance(
                error,
                str,
            )
            or not error.strip()
        ):
            raise ValueError(
                "failed MetricPublicationResult "
                "requires an error"
            )

        raise RuntimeError(
            "Metric publication failed: "
            + error.strip()
        )

    if document[
        "error"
    ] is not None:
        raise ValueError(
            "successful MetricPublicationResult "
            "cannot contain an error"
        )

    accepted = document[
        "accepted"
    ]

    if not isinstance(
        accepted,
        bool,
    ):
        raise TypeError(
            "MetricPublicationResult.accepted "
            "must be a bool"
        )

    return MetricPublishResult(
        accepted=accepted,
        reason=document[
            "reason"
        ],
    )


__all__ = [
    "METRIC_PUBLICATION_API_VERSION",
    "METRIC_PUBLICATION_KIND",
    "METRIC_PUBLICATION_RESULT_API_VERSION",
    "METRIC_PUBLICATION_RESULT_KIND",
    "metric_from_publication_document",
    "metric_publication_document",
    "metric_publication_result_document",
    "metric_publish_result_from_document",
]
