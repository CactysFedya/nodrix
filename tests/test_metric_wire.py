from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

import pytest

from nodrix.metric_publisher import (
    MetricPublishResult,
)
from nodrix.metric_wire import (
    metric_from_publication_document,
    metric_publication_document,
    metric_publication_result_document,
    metric_publish_result_from_document,
)
from nodrix.model import (
    MetricDescriptor,
    MetricRecord,
)


NOW = datetime(
    2026,
    8,
    19,
    6,
    30,
    tzinfo=timezone.utc,
)


def _metric() -> MetricRecord:
    return MetricRecord(
        descriptor=MetricDescriptor(
            name="detector.inference_ms",
            value_type="float",
            unit="ms",
        ),
        value=12.5,
        observed_at=NOW,
        source="detector",
        attributes={
            "model": "yolo26n",
        },
    )


def test_metric_publication_roundtrip_is_typed() -> None:
    metric = _metric()

    restored = (
        metric_from_publication_document(
            metric_publication_document(
                metric
            )
        )
    )

    assert isinstance(
        restored,
        MetricRecord,
    )
    assert (
        restored.descriptor_id
        == metric.descriptor_id
    )
    assert restored.value == 12.5
    assert restored.source == "detector"
    assert dict(
        restored.attributes
    ) == {
        "model": "yolo26n",
    }


def test_metric_publication_rejects_tampered_descriptor_identity() -> None:
    document = (
        metric_publication_document(
            _metric()
        )
    )

    document[
        "metric"
    ][
        "descriptor"
    ][
        "descriptorId"
    ] = "metric-tampered"

    with pytest.raises(
        ValueError,
        match="descriptorId",
    ):
        metric_from_publication_document(
            document
        )


@pytest.mark.parametrize(
    (
        "result",
        "expected",
    ),
    (
        (
            MetricPublishResult(
                accepted=True
            ),
            (
                True,
                None,
            ),
        ),
        (
            MetricPublishResult(
                accepted=False,
                reason="record-limit",
            ),
            (
                False,
                "record-limit",
            ),
        ),
    ),
)
def test_metric_publication_result_roundtrip(
    result,
    expected,
) -> None:
    restored = (
        metric_publish_result_from_document(
            metric_publication_result_document(
                result
            )
        )
    )

    assert (
        restored.accepted,
        restored.reason,
    ) == expected


def test_metric_publication_transport_error_is_not_a_drop() -> None:
    document = (
        metric_publication_result_document(
            error="invalid provenance"
        )
    )

    with pytest.raises(
        RuntimeError,
        match="invalid provenance",
    ):
        metric_publish_result_from_document(
            document
        )
