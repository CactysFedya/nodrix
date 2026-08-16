"""Canonical bridge for resolved Nodrix optimization plans."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .benchmark_canonical import (
    benchmark_plan_digest,
)
from .model import (
    OPTIMIZATION_PLAN,
    Operation,
    PlanRecord,
    RevisionRef,
    canonical_plan_id,
)
from .optimization import OptimizationPlan


def optimization_plan_digest(
    plan: OptimizationPlan,
) -> str:
    """Return the semantic digest of one resolved optimization plan."""

    if not isinstance(
        plan,
        OptimizationPlan,
    ):
        raise TypeError(
            "plan must be an OptimizationPlan"
        )

    payload = {
        "pipeline_name": (
            plan.pipeline_name
        ),
        "run_benchmarks": (
            plan.run_benchmarks
        ),
        "objectives": dict(
            plan.objectives
        ),
        "constraints": dict(
            plan.constraints
        ),
        "benchmark_plan_sha256": (
            benchmark_plan_digest(
                plan.benchmark_plan
            )
        ),
    }

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def optimization_plan_record(
    plan: OptimizationPlan,
    *,
    operation: Operation,
    subject_revision: RevisionRef,
    metadata: Mapping[str, Any] | None = None,
) -> PlanRecord:
    """Wrap one exact optimization plan in the canonical envelope."""

    if not isinstance(
        plan,
        OptimizationPlan,
    ):
        raise TypeError(
            "plan must be an OptimizationPlan"
        )

    if not isinstance(
        operation,
        Operation,
    ):
        raise TypeError(
            "operation must be an Operation"
        )

    if not isinstance(
        subject_revision,
        RevisionRef,
    ):
        raise TypeError(
            "subject_revision must be a RevisionRef"
        )

    if (
        subject_revision.entity
        != operation.subject
    ):
        raise ValueError(
            "subject_revision must reference "
            "the operation subject"
        )

    digest = optimization_plan_digest(
        plan
    )

    benchmark_digest = (
        benchmark_plan_digest(
            plan.benchmark_plan
        )
    )

    canonical_metadata = {
        **dict(metadata or {}),
        "optimization_digest": digest,
        "benchmark_plan_sha256": (
            benchmark_digest
        ),
        "pipeline": (
            plan.pipeline_name
        ),
        "run_benchmarks": (
            plan.run_benchmarks
        ),
        "variant_count": len(
            plan.variants
        ),
    }

    return PlanRecord(
        plan_id=canonical_plan_id(
            kind=OPTIMIZATION_PLAN,
            operation=operation,
            subject_revision=subject_revision,
            payload_sha256=digest,
        ),
        kind=OPTIMIZATION_PLAN,
        operation=operation,
        subject_revision=subject_revision,
        payload=plan,
        metadata=canonical_metadata,
    )


__all__ = [
    "optimization_plan_digest",
    "optimization_plan_record",
]
