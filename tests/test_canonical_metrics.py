from __future__ import annotations

from dataclasses import (
    FrozenInstanceError,
    fields,
)
from datetime import (
    datetime,
    timezone,
)

import pytest

from nodrix.model import (
    MetricDescriptor,
    MetricRecord,
    MetricValueType,
    canonical_metric_descriptor_id,
)


NOW = datetime(
    2026,
    8,
    19,
    8,
    50,
    tzinfo=timezone.utc,
)


def test_metric_descriptor_identity_is_deterministic_and_semantic() -> None:
    first = MetricDescriptor(
        name="mapping.update_ms",
        value_type="float",
        unit="ms",
        description="First documentation",
    )

    second = MetricDescriptor(
        name="mapping.update_ms",
        value_type=MetricValueType.FLOAT,
        unit="ms",
        description="Changed documentation",
    )

    assert (
        first.descriptor_id
        == second.descriptor_id
    )

    assert first.descriptor_id == (
        canonical_metric_descriptor_id(
            name="mapping.update_ms",
            value_type="float",
            unit="ms",
        )
    )

    assert (
        first.descriptor_id
        != MetricDescriptor(
            name="mapping.update_ms",
            value_type="float",
            unit="s",
        ).descriptor_id
    )


def test_custom_namespaced_metric_is_supported() -> None:
    descriptor = MetricDescriptor(
        name=(
            "acme.detector.inference_ms"
        ),
        value_type="float",
        unit="ms",
    )

    assert (
        descriptor.name
        == "acme.detector.inference_ms"
    )


def test_metric_descriptor_is_immutable() -> None:
    descriptor = MetricDescriptor(
        name="sdk.frames",
        value_type="integer",
        unit="count",
    )

    with pytest.raises(
        FrozenInstanceError,
    ):
        descriptor.name = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    (
        True,
        1.0,
        "1",
        {},
    ),
)
def test_integer_metric_rejects_non_integer_values(
    value,
) -> None:
    descriptor = MetricDescriptor(
        name="sdk.frames",
        value_type="integer",
        unit="count",
    )

    with pytest.raises(
        TypeError,
    ):
        MetricRecord(
            descriptor=descriptor,
            value=value,
            observed_at=NOW,
        )


def test_integer_metric_accepts_int_without_boolean_coercion() -> None:
    record = MetricRecord(
        descriptor=MetricDescriptor(
            name="sdk.frames",
            value_type="integer",
            unit="count",
        ),
        value=42,
        observed_at=NOW,
    )

    assert record.value == 42
    assert isinstance(
        record.value,
        int,
    )


@pytest.mark.parametrize(
    "value",
    (
        1,
        1.5,
    ),
)
def test_float_metric_accepts_numeric_values_and_canonicalizes(
    value,
) -> None:
    record = MetricRecord(
        descriptor=MetricDescriptor(
            name="mapping.update_ms",
            value_type="float",
            unit="ms",
        ),
        value=value,
        observed_at=NOW,
    )

    assert isinstance(
        record.value,
        float,
    )

    assert record.value == float(
        value
    )


@pytest.mark.parametrize(
    "value",
    (
        float("nan"),
        float("inf"),
        float("-inf"),
    ),
)
def test_float_metric_rejects_non_finite_values(
    value,
) -> None:
    descriptor = MetricDescriptor(
        name="mapping.update_ms",
        value_type="float",
        unit="ms",
    )

    with pytest.raises(
        ValueError,
        match="finite",
    ):
        MetricRecord(
            descriptor=descriptor,
            value=value,
            observed_at=NOW,
        )


def test_float_metric_rejects_boolean_and_arbitrary_json() -> None:
    descriptor = MetricDescriptor(
        name="mapping.update_ms",
        value_type="float",
        unit="ms",
    )

    for value in (
        True,
        "12.5",
        [12.5],
        {
            "value": 12.5,
        },
    ):
        with pytest.raises(
            TypeError,
        ):
            MetricRecord(
                descriptor=descriptor,
                value=value,
                observed_at=NOW,
            )


def test_metric_timestamp_must_be_timezone_aware() -> None:
    descriptor = MetricDescriptor(
        name="mapping.voxels",
        value_type="integer",
        unit="count",
    )

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        MetricRecord(
            descriptor=descriptor,
            value=10,
            observed_at=datetime(
                2026,
                8,
                19,
                8,
                50,
            ),
        )


def test_metric_source_is_optional_but_non_empty_when_present() -> None:
    descriptor = MetricDescriptor(
        name="mapping.voxels",
        value_type="integer",
        unit="count",
    )

    assert MetricRecord(
        descriptor=descriptor,
        value=10,
        observed_at=NOW,
    ).source is None

    with pytest.raises(
        ValueError,
        match="metric source",
    ):
        MetricRecord(
            descriptor=descriptor,
            value=10,
            observed_at=NOW,
            source="   ",
        )


def test_metric_attributes_are_string_only_canonical_and_immutable() -> None:
    source = {
        "stage": " integration ",
        "sensor": "mid360",
    }

    record = MetricRecord(
        descriptor=MetricDescriptor(
            name="mapping.update_ms",
            value_type="float",
            unit="ms",
        ),
        value=12.5,
        observed_at=NOW,
        attributes=source,
    )

    source[
        "stage"
    ] = "changed"

    assert dict(
        record.attributes
    ) == {
        "sensor": "mid360",
        "stage": "integration",
    }

    with pytest.raises(
        TypeError,
    ):
        record.attributes[
            "stage"
        ] = "other"  # type: ignore[index]


@pytest.mark.parametrize(
    "attributes",
    (
        {
            "attempt": 1,
        },
        {
            "active": True,
        },
        {
            "nested": {
                "x": "y",
            },
        },
    ),
)
def test_metric_attributes_reject_non_string_values(
    attributes,
) -> None:
    with pytest.raises(
        TypeError,
        match="must be strings",
    ):
        MetricRecord(
            descriptor=MetricDescriptor(
                name="sdk.frames",
                value_type="integer",
                unit="count",
            ),
            value=1,
            observed_at=NOW,
            attributes=attributes,
        )


def test_metric_record_contains_no_run_log_event_or_artifact_fields() -> None:
    names = {
        item.name
        for item in fields(
            MetricRecord
        )
    }

    assert names == {
        "descriptor",
        "value",
        "observed_at",
        "source",
        "attributes",
    }

    forbidden = {
        "run_id",
        "sequence",
        "log",
        "category",
        "event",
        "artifact",
        "path",
        "prometheus",
    }

    assert forbidden.isdisjoint(
        names
    )
