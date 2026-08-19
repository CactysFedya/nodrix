from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)

import pytest

from nodrix.metric_publisher import (
    BoundMetric,
    MetricPublishResult,
    MetricPublisher,
)
from nodrix.model import (
    MetricRecord,
)
from nodrix.node import (
    NodeContext,
)
from nodrix.sdk import (
    MetricPublisher as SDKMetricPublisher,
)


NOW = datetime(
    2026,
    8,
    19,
    6,
    10,
    tzinfo=timezone.utc,
)


class CollectingSink:
    def __init__(
        self,
        *,
        accepted: bool = True,
        reason: str | None = None,
    ) -> None:
        self.records: list[
            MetricRecord
        ] = []
        self.accepted = accepted
        self.reason = reason

    def publish(
        self,
        metric: MetricRecord,
    ) -> MetricPublishResult:
        self.records.append(
            metric
        )

        return MetricPublishResult(
            accepted=self.accepted,
            reason=self.reason,
        )


def test_publisher_creates_canonical_metric_record() -> None:
    sink = CollectingSink()

    publisher = MetricPublisher(
        source="detector",
        sink=sink,
        clock=lambda: NOW,
    )

    result = publisher.observe(
        "detector.inference_ms",
        12.5,
        value_type="float",
        unit="ms",
        attributes={
            "model": "yolo26n",
        },
    )

    assert result == MetricPublishResult(
        accepted=True
    )

    assert len(
        sink.records
    ) == 1

    metric = sink.records[0]

    assert isinstance(
        metric,
        MetricRecord,
    )

    assert (
        metric.name
        == "detector.inference_ms"
    )
    assert metric.value == 12.5
    assert metric.unit == "ms"
    assert metric.source == "detector"
    assert metric.observed_at == NOW

    assert dict(
        metric.attributes
    ) == {
        "model": "yolo26n",
    }


def test_bound_metric_reuses_descriptor() -> None:
    sink = CollectingSink()

    publisher = MetricPublisher(
        source="mapping.voxel_map",
        sink=sink,
        clock=lambda: NOW,
    )

    first = publisher.metric(
        "mapping.update_ms",
        value_type="float",
        unit="ms",
    )

    second = publisher.metric(
        "mapping.update_ms",
        value_type="float",
        unit="ms",
    )

    assert isinstance(
        first,
        BoundMetric,
    )

    assert first is second

    assert first.observe(
        1.5
    ).accepted

    assert first.observe(
        2.0
    ).accepted

    assert len(
        sink.records
    ) == 2

    assert (
        sink.records[0].descriptor
        is sink.records[1].descriptor
    )


def test_default_publisher_is_nonfatal_disabled_sink() -> None:
    publisher = MetricPublisher(
        source="component",
        clock=lambda: NOW,
    )

    result = publisher.observe(
        "component.frames",
        1,
        value_type="integer",
        unit="count",
    )

    assert not result.accepted
    assert result.reason == "disabled"


def test_invalid_metric_still_raises_before_sink() -> None:
    sink = CollectingSink()

    publisher = MetricPublisher(
        source="detector",
        sink=sink,
        clock=lambda: NOW,
    )

    with pytest.raises(
        TypeError,
    ):
        publisher.observe(
            "detector.inference_ms",
            True,
            value_type="float",
            unit="ms",
        )

    assert sink.records == []


def test_sink_drop_is_result_not_execution_exception() -> None:
    sink = CollectingSink(
        accepted=False,
        reason="record-limit",
    )

    publisher = MetricPublisher(
        source="detector",
        sink=sink,
        clock=lambda: NOW,
    )

    result = publisher.observe(
        "detector.frames",
        1,
        value_type="integer",
        unit="count",
    )

    assert not result.accepted
    assert (
        result.reason
        == "record-limit"
    )


def test_node_context_exposes_stable_metric_publisher(
    tmp_path,
) -> None:
    context = NodeContext(
        name="detector",
        run_dir=tmp_path / "run",
        project_dir=tmp_path,
        runtime_mode="test",
    )

    first = context.metrics
    second = context.metrics

    assert isinstance(
        first,
        MetricPublisher,
    )

    assert first is second
    assert first.source == "detector"

    result = first.observe(
        "detector.frames",
        1,
        value_type="integer",
        unit="count",
        observed_at=NOW,
    )

    assert not result.accepted
    assert result.reason == "disabled"


def test_executor_can_bind_metric_sink_without_exposing_storage(
    tmp_path,
) -> None:
    sink = CollectingSink()

    context = NodeContext(
        name="mapping",
        run_dir=tmp_path / "run",
        project_dir=tmp_path,
        runtime_mode="test",
    )

    context._bind_metric_sink(  # noqa: SLF001
        sink
    )

    result = context.metrics.observe(
        "mapping.voxels",
        42,
        value_type="integer",
        unit="count",
        observed_at=NOW,
    )

    assert result.accepted
    assert len(
        sink.records
    ) == 1
    assert (
        sink.records[0].source
        == "mapping"
    )


def test_sdk_exports_metric_publisher() -> None:
    assert (
        SDKMetricPublisher
        is MetricPublisher
    )


def test_publish_result_contract_is_strict() -> None:
    with pytest.raises(
        ValueError,
    ):
        MetricPublishResult(
            accepted=False,
            reason=None,
        )

    with pytest.raises(
        ValueError,
    ):
        MetricPublishResult(
            accepted=True,
            reason="unexpected",
        )


    with pytest.raises(
        TypeError,
    ):
        MetricPublishResult(
            accepted=False,
            reason=123,  # type: ignore[arg-type]
        )
