"""Canonical comparison model for immutable Nodrix Runs.

This module compares canonical ``RunRecord`` values only.

It deliberately does not read legacy Pipeline summaries, filesystem state,
Metric journals, or CLI presentation.  Persistence loading and compatibility
dispatch belong to higher layers.

Different Run and Execution identities are expected when the same Plan is
executed repeatedly.  Plan identity, subject revision, Operation semantics and
executor identity are therefore compared independently from Run identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

from .model import RunRecord
from .run_bundle import CanonicalRunBundle
from .run_metric_comparison import (
    RunMetricsComparison,
    compare_run_metrics,
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


def _enum_text(
    value: Any,
) -> str:
    raw = getattr(
        value,
        "value",
        value,
    )

    return _required_text(
        raw,
        field_name="enum value",
    )


def _duration_seconds(
    run: RunRecord,
) -> float:
    duration = (
        run.finished_at
        - run.started_at
    ).total_seconds()

    if (
        not isfinite(duration)
        or duration < 0.0
    ):
        raise ValueError(
            "Run duration must be finite "
            "and non-negative"
        )

    return float(duration)


def _delta(
    first: float,
    second: float,
) -> tuple[
    float,
    float | None,
]:
    delta = second - first

    percent = (
        None
        if first == 0.0
        else (
            delta
            / abs(first)
            * 100.0
        )
    )

    return (
        delta,
        percent,
    )


@dataclass(
    frozen=True,
    slots=True,
)
class RunComparisonSide:
    """Stable identity/outcome projection of one canonical Run."""

    run_id: str
    execution_id: str
    plan_id: str
    operation_kind: str
    state: str
    successful: bool
    executor: str
    duration_seconds: float

    def __post_init__(
        self,
    ) -> None:
        for field_name in (
            "run_id",
            "execution_id",
            "plan_id",
            "operation_kind",
            "state",
            "executor",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(
                    getattr(
                        self,
                        field_name,
                    ),
                    field_name=field_name,
                ),
            )

        if not isinstance(
            self.successful,
            bool,
        ):
            raise TypeError(
                "successful must be a bool"
            )

        if (
            not isinstance(
                self.duration_seconds,
                (int, float),
            )
            or isinstance(
                self.duration_seconds,
                bool,
            )
        ):
            raise TypeError(
                "duration_seconds must be numeric"
            )

        duration = float(
            self.duration_seconds
        )

        if (
            not isfinite(duration)
            or duration < 0.0
        ):
            raise ValueError(
                "duration_seconds must be finite "
                "and non-negative"
            )

        object.__setattr__(
            self,
            "duration_seconds",
            duration,
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "runId": self.run_id,
            "executionId": self.execution_id,
            "planId": self.plan_id,
            "operationKind": (
                self.operation_kind
            ),
            "state": self.state,
            "successful": self.successful,
            "executor": self.executor,
            "durationSeconds": (
                self.duration_seconds
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class RunProvenanceComparison:
    """Semantic/provenance relationship between two Runs."""

    same_subject: bool
    same_subject_revision: bool
    same_operation: bool
    same_plan: bool
    same_executor: bool

    def __post_init__(
        self,
    ) -> None:
        for field_name in (
            "same_subject",
            "same_subject_revision",
            "same_operation",
            "same_plan",
            "same_executor",
        ):
            if not isinstance(
                getattr(
                    self,
                    field_name,
                ),
                bool,
            ):
                raise TypeError(
                    f"{field_name} must be a bool"
                )

    @property
    def same_workload(
        self,
    ) -> bool:
        """Whether both Runs represent the same exact planned workload."""

        return (
            self.same_subject_revision
            and self.same_operation
            and self.same_plan
        )

    def to_dict(
        self,
    ) -> dict[str, bool]:
        return {
            "sameSubject": (
                self.same_subject
            ),
            "sameSubjectRevision": (
                self.same_subject_revision
            ),
            "sameOperation": (
                self.same_operation
            ),
            "samePlan": (
                self.same_plan
            ),
            "sameExecutor": (
                self.same_executor
            ),
            "sameWorkload": (
                self.same_workload
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class RunOutcomeComparison:
    """Terminal outcome and duration comparison."""

    same_state: bool
    both_successful: bool
    duration_delta_seconds: float
    duration_percent: float | None

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.same_state,
            bool,
        ):
            raise TypeError(
                "same_state must be a bool"
            )

        if not isinstance(
            self.both_successful,
            bool,
        ):
            raise TypeError(
                "both_successful must be a bool"
            )

        for field_name in (
            "duration_delta_seconds",
            "duration_percent",
        ):
            value = getattr(
                self,
                field_name,
            )

            if value is None:
                continue

            if (
                not isinstance(
                    value,
                    (int, float),
                )
                or isinstance(
                    value,
                    bool,
                )
            ):
                raise TypeError(
                    f"{field_name} must be numeric "
                    "or None"
                )

            canonical = float(
                value
            )

            if not isfinite(
                canonical
            ):
                raise ValueError(
                    f"{field_name} must be finite"
                )

            object.__setattr__(
                self,
                field_name,
                canonical,
            )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "sameState": self.same_state,
            "bothSuccessful": (
                self.both_successful
            ),
            "durationDeltaSeconds": (
                self.duration_delta_seconds
            ),
            "durationPercent": (
                self.duration_percent
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalRunComparison:
    """Typed comparison result for two canonical Runs."""

    first: RunComparisonSide
    second: RunComparisonSide
    provenance: RunProvenanceComparison
    outcome: RunOutcomeComparison

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.first,
            RunComparisonSide,
        ):
            raise TypeError(
                "first must be a RunComparisonSide"
            )

        if not isinstance(
            self.second,
            RunComparisonSide,
        ):
            raise TypeError(
                "second must be a RunComparisonSide"
            )

        if not isinstance(
            self.provenance,
            RunProvenanceComparison,
        ):
            raise TypeError(
                "provenance must be a "
                "RunProvenanceComparison"
            )

        if not isinstance(
            self.outcome,
            RunOutcomeComparison,
        ):
            raise TypeError(
                "outcome must be a "
                "RunOutcomeComparison"
            )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "first": self.first.to_dict(),
            "second": self.second.to_dict(),
            "provenance": (
                self.provenance.to_dict()
            ),
            "outcome": (
                self.outcome.to_dict()
            ),
        }


def _side(
    run: RunRecord,
) -> RunComparisonSide:
    if not isinstance(
        run,
        RunRecord,
    ):
        raise TypeError(
            "run must be a RunRecord"
        )

    return RunComparisonSide(
        run_id=run.run_id,
        execution_id=run.execution_id,
        plan_id=run.plan.plan_id,
        operation_kind=_enum_text(
            run.operation.kind
        ),
        state=_enum_text(
            run.state
        ),
        successful=run.successful,
        executor=run.execution.executor,
        duration_seconds=(
            _duration_seconds(
                run
            )
        ),
    )


def compare_run_records(
    first: RunRecord,
    second: RunRecord,
) -> CanonicalRunComparison:
    """Compare two immutable canonical Run records.

    Run identity is intentionally not used to determine semantic
    comparability.  Repeated executions of the same exact Plan are distinct
    Runs and Executions but may still represent the same workload.
    """

    if not isinstance(
        first,
        RunRecord,
    ):
        raise TypeError(
            "first must be a RunRecord"
        )

    if not isinstance(
        second,
        RunRecord,
    ):
        raise TypeError(
            "second must be a RunRecord"
        )

    first_side = _side(
        first
    )
    second_side = _side(
        second
    )

    duration_delta, duration_percent = (
        _delta(
            first_side.duration_seconds,
            second_side.duration_seconds,
        )
    )

    return CanonicalRunComparison(
        first=first_side,
        second=second_side,
        provenance=RunProvenanceComparison(
            same_subject=(
                first.subject
                == second.subject
            ),
            same_subject_revision=(
                first.subject_revision
                == second.subject_revision
            ),
            same_operation=(
                first.operation
                == second.operation
            ),
            same_plan=(
                first.plan.plan_id
                == second.plan.plan_id
            ),
            same_executor=(
                first.execution.executor
                == second.execution.executor
            ),
        ),
        outcome=RunOutcomeComparison(
            same_state=(
                first.state
                == second.state
            ),
            both_successful=(
                first.successful
                and second.successful
            ),
            duration_delta_seconds=(
                duration_delta
            ),
            duration_percent=(
                duration_percent
            ),
        ),
    )


def _plain_json(
    value: Any,
) -> Any:
    """Return a deterministic plain representation of frozen JSON."""

    if isinstance(
        value,
        Mapping,
    ):
        return {
            key: _plain_json(
                item
            )
            for key, item
            in value.items()
        }

    if isinstance(
        value,
        (tuple, list),
    ):
        return [
            _plain_json(
                item
            )
            for item in value
        ]

    return value


def _snapshot_content(
    document: Mapping[str, Any],
    *,
    field_name: str,
) -> dict[str, Any]:
    content = document.get(
        "content"
    )

    if not isinstance(
        content,
        Mapping,
    ):
        raise TypeError(
            f"{field_name} content must be a mapping"
        )

    plain = _plain_json(
        content
    )

    if not isinstance(
        plain,
        dict,
    ):
        raise TypeError(
            f"{field_name} content must be an object"
        )

    return plain


def _policy_semantics(
    policy: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Normalize effective policy independently from Run/storage identity.

    runId, planId and storage apiVersion are provenance envelope fields rather
    than ExecutionPolicy semantics.  Historical policy v1 therefore compares
    equal to v2 when environment/logs are equal and v2 metrics are disabled.
    """

    if policy is None:
        return None

    return {
        "environment": _plain_json(
            policy.get(
                "environment"
            )
        ),
        "logs": _plain_json(
            policy.get(
                "logs"
            )
        ),
        "metrics": _plain_json(
            policy.get(
                "metrics"
            )
        ),
    }


def _persisted_timestamp(
    value: object,
    *,
    field_name: str,
) -> datetime:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            f"{field_name} must be a string"
        )

    text = value.strip()

    if not text:
        raise ValueError(
            f"{field_name} must be non-empty"
        )

    try:
        parsed = datetime.fromisoformat(
            (
                text[:-1] + "+00:00"
                if text.endswith("Z")
                else text
            )
        )
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc

    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be timezone-aware"
        )

    return parsed.astimezone(
        timezone.utc
    )


def _bundle_side(
    bundle: CanonicalRunBundle,
) -> RunComparisonSide:
    execution = bundle.run.get(
        "execution"
    )

    if not isinstance(
        execution,
        Mapping,
    ):
        raise TypeError(
            "bundle run execution must be a mapping"
        )

    started = _persisted_timestamp(
        execution.get(
            "startedAt"
        ),
        field_name=(
            "run execution.startedAt"
        ),
    )

    finished = _persisted_timestamp(
        execution.get(
            "finishedAt"
        ),
        field_name=(
            "run execution.finishedAt"
        ),
    )

    duration = (
        finished
        - started
    ).total_seconds()

    successful = execution.get(
        "successful"
    )

    if not isinstance(
        successful,
        bool,
    ):
        raise TypeError(
            "run execution.successful must be a bool"
        )

    return RunComparisonSide(
        run_id=bundle.session.run_id,
        execution_id=_required_text(
            execution.get(
                "executionId"
            ),
            field_name="execution_id",
        ),
        plan_id=bundle.session.plan_id,
        operation_kind=(
            bundle.session.operation_kind
        ),
        state=_required_text(
            execution.get(
                "state"
            ),
            field_name="state",
        ),
        successful=successful,
        executor=_required_text(
            execution.get(
                "executor"
            ),
            field_name="executor",
        ),
        duration_seconds=duration,
    )


def _persisted_operation_semantics(
    bundle: CanonicalRunBundle,
) -> Any:
    content = _snapshot_content(
        bundle.plan,
        field_name="plan",
    )

    operation = content.get(
        "operation"
    )

    if operation is not None:
        return _plain_json(
            operation
        )

    # Historical/future generic Plan snapshot domains may not expose a
    # dedicated operation object.  Session identity still records the
    # operation kind and subject provenance.
    return {
        "kind": (
            bundle.session.operation_kind
        ),
        "subject": (
            bundle.session.subject
        ),
        "subjectRevision": (
            bundle.session.subject_revision
        ),
    }


@dataclass(
    frozen=True,
    slots=True,
)
class RunEvidenceComparison:
    """Comparison of immutable persisted evidence attached to two Runs."""

    same_definition: bool
    same_plan_snapshot: bool
    first_policy_available: bool
    second_policy_available: bool
    same_effective_policy: bool | None

    def __post_init__(
        self,
    ) -> None:
        for field_name in (
            "same_definition",
            "same_plan_snapshot",
            "first_policy_available",
            "second_policy_available",
        ):
            if not isinstance(
                getattr(
                    self,
                    field_name,
                ),
                bool,
            ):
                raise TypeError(
                    f"{field_name} must be a bool"
                )

        if (
            self.same_effective_policy
            is not None
            and not isinstance(
                self.same_effective_policy,
                bool,
            )
        ):
            raise TypeError(
                "same_effective_policy must be a bool or None"
            )

        expected_comparable = (
            self.first_policy_available
            and self.second_policy_available
        )

        if (
            not expected_comparable
            and self.same_effective_policy
            is not None
        ):
            raise ValueError(
                "same_effective_policy must be None "
                "when policy evidence is unavailable"
            )

    @property
    def policy_comparable(
        self,
    ) -> bool:
        return (
            self.first_policy_available
            and self.second_policy_available
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "sameDefinition": (
                self.same_definition
            ),
            "samePlanSnapshot": (
                self.same_plan_snapshot
            ),
            "firstPolicyAvailable": (
                self.first_policy_available
            ),
            "secondPolicyAvailable": (
                self.second_policy_available
            ),
            "policyComparable": (
                self.policy_comparable
            ),
            "samePolicy": (
                self.same_effective_policy
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalRunBundleComparison:
    """Comparison of two complete persisted canonical Run bundles."""

    runs: CanonicalRunComparison
    evidence: RunEvidenceComparison
    metrics: RunMetricsComparison

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.runs,
            CanonicalRunComparison,
        ):
            raise TypeError(
                "runs must be a CanonicalRunComparison"
            )

        if not isinstance(
            self.evidence,
            RunEvidenceComparison,
        ):
            raise TypeError(
                "evidence must be a RunEvidenceComparison"
            )

        if not isinstance(
            self.metrics,
            RunMetricsComparison,
        ):
            raise TypeError(
                "metrics must be a RunMetricsComparison"
            )

    @property
    def same_exact_workload(
        self,
    ) -> bool:
        """Whether immutable Definition + exact resolved Plan are identical."""

        return (
            self.runs.provenance.same_workload
            and self.evidence.same_definition
            and self.evidence.same_plan_snapshot
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        document = (
            self.runs.to_dict()
        )

        evidence = (
            self.evidence.to_dict()
        )

        evidence[
            "sameExactWorkload"
        ] = (
            self.same_exact_workload
        )

        document[
            "evidence"
        ] = evidence

        document[
            "metrics"
        ] = (
            self.metrics.to_dict()
        )

        return document


def compare_canonical_run_bundles(
    first: CanonicalRunBundle,
    second: CanonicalRunBundle,
) -> CanonicalRunBundleComparison:
    """Compare complete persisted evidence for two canonical Runs."""

    if not isinstance(
        first,
        CanonicalRunBundle,
    ):
        raise TypeError(
            "first must be a CanonicalRunBundle"
        )

    if not isinstance(
        second,
        CanonicalRunBundle,
    ):
        raise TypeError(
            "second must be a CanonicalRunBundle"
        )

    first_side = _bundle_side(
        first
    )

    second_side = _bundle_side(
        second
    )

    (
        duration_delta,
        duration_percent,
    ) = _delta(
        first_side.duration_seconds,
        second_side.duration_seconds,
    )

    run_comparison = (
        CanonicalRunComparison(
            first=first_side,
            second=second_side,
            provenance=(
                RunProvenanceComparison(
                    same_subject=(
                        first.session.subject
                        == second.session.subject
                    ),
                    same_subject_revision=(
                        first.session.subject_revision
                        == second.session.subject_revision
                    ),
                    same_operation=(
                        _persisted_operation_semantics(
                            first
                        )
                        == _persisted_operation_semantics(
                            second
                        )
                    ),
                    same_plan=(
                        first.session.plan_id
                        == second.session.plan_id
                    ),
                    same_executor=(
                        first_side.executor
                        == second_side.executor
                    ),
                )
            ),
            outcome=RunOutcomeComparison(
                same_state=(
                    first_side.state
                    == second_side.state
                ),
                both_successful=(
                    first_side.successful
                    and second_side.successful
                ),
                duration_delta_seconds=(
                    duration_delta
                ),
                duration_percent=(
                    duration_percent
                ),
            ),
        )
    )

    first_policy = _policy_semantics(
        first.policy
    )

    second_policy = _policy_semantics(
        second.policy
    )

    both_policies_available = (
        first_policy is not None
        and second_policy is not None
    )

    evidence = RunEvidenceComparison(
        same_definition=(
            _snapshot_content(
                first.definition,
                field_name="definition",
            )
            == _snapshot_content(
                second.definition,
                field_name="definition",
            )
        ),
        same_plan_snapshot=(
            _snapshot_content(
                first.plan,
                field_name="plan",
            )
            == _snapshot_content(
                second.plan,
                field_name="plan",
            )
        ),
        first_policy_available=(
            first_policy is not None
        ),
        second_policy_available=(
            second_policy is not None
        ),
        same_effective_policy=(
            (
                first_policy
                == second_policy
            )
            if both_policies_available
            else None
        ),
    )

    return CanonicalRunBundleComparison(
        runs=run_comparison,
        evidence=evidence,
        metrics=compare_run_metrics(
            first,
            second,
        ),
    )


__all__ = [
    "CanonicalRunBundleComparison",
    "CanonicalRunComparison",
    "RunComparisonSide",
    "RunEvidenceComparison",
    "RunOutcomeComparison",
    "RunProvenanceComparison",
    "compare_canonical_run_bundles",
    "compare_run_records",
]
