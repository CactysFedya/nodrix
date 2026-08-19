from __future__ import annotations

import pytest

from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.run_metric_policy import (
    RunMetricPolicy,
)
from nodrix.run_policy import (
    RUN_POLICY_API_VERSION,
    RUN_POLICY_V1_API_VERSION,
    RunPolicyCorruptionError,
    execution_policy_document,
    validate_execution_policy_document,
)


RUN_ID = "run_metric_policy"
PLAN_ID = "plan_metric_policy"


def test_execution_policy_disables_canonical_metrics_by_default() -> None:
    policy = ExecutionPolicy()

    assert policy.metrics is None

    document = (
        execution_policy_document(
            policy,
            run_id=RUN_ID,
            plan_id=PLAN_ID,
        )
    )

    assert (
        document["apiVersion"]
        == RUN_POLICY_API_VERSION
    )
    assert (
        document["metrics"]
        is None
    )

    assert (
        validate_execution_policy_document(
            document,
            run_id=RUN_ID,
            plan_id=PLAN_ID,
        )
        == document
    )


def test_execution_policy_persists_exact_metric_limits() -> None:
    metrics = RunMetricPolicy(
        max_records=17,
        max_bytes=8192,
        max_record_bytes=1024,
        overflow="drop",
    )

    policy = ExecutionPolicy(
        metrics=metrics
    )

    document = (
        execution_policy_document(
            policy,
            run_id=RUN_ID,
            plan_id=PLAN_ID,
        )
    )

    assert document[
        "metrics"
    ] == {
        "maxRecords": 17,
        "maxBytes": 8192,
        "maxRecordBytes": 1024,
        "overflow": "drop",
    }

    assert (
        validate_execution_policy_document(
            document,
            run_id=RUN_ID,
            plan_id=PLAN_ID,
        )
        == document
    )


def test_policy_reader_remains_backward_compatible_with_v1() -> None:
    document = (
        execution_policy_document(
            ExecutionPolicy(),
            run_id=RUN_ID,
            plan_id=PLAN_ID,
        )
    )

    document.pop(
        "metrics"
    )
    document[
        "apiVersion"
    ] = RUN_POLICY_V1_API_VERSION

    restored = (
        validate_execution_policy_document(
            document,
            run_id=RUN_ID,
            plan_id=PLAN_ID,
        )
    )

    assert (
        restored["apiVersion"]
        == RUN_POLICY_V1_API_VERSION
    )
    assert "metrics" not in restored


@pytest.mark.parametrize(
    "metrics",
    (
        {},
        {
            "maxRecords": 1,
            "maxBytes": 1024,
            "maxRecordBytes": 128,
            "overflow": "block",
        },
        {
            "maxRecords": True,
            "maxBytes": 1024,
            "maxRecordBytes": 128,
            "overflow": "drop",
        },
        {
            "maxRecords": 1,
            "maxBytes": 128,
            "maxRecordBytes": 1024,
            "overflow": "drop",
        },
    ),
)
def test_policy_v2_rejects_invalid_metric_contract(
    metrics,
) -> None:
    document = (
        execution_policy_document(
            ExecutionPolicy(),
            run_id=RUN_ID,
            plan_id=PLAN_ID,
        )
    )

    document[
        "metrics"
    ] = metrics

    with pytest.raises(
        RunPolicyCorruptionError,
    ):
        validate_execution_policy_document(
            document,
            run_id=RUN_ID,
            plan_id=PLAN_ID,
        )


def test_execution_policy_rejects_non_metric_policy() -> None:
    with pytest.raises(
        TypeError,
        match="metrics",
    ):
        ExecutionPolicy(
            metrics=object(),  # type: ignore[arg-type]
        )
