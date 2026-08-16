"""Canonical bridge for Nodrix benchmark plans."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .benchmarking import BenchmarkPlan
from .model import (
    BENCHMARK_PLAN,
    Operation,
    PlanRecord,
    RevisionRef,
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def benchmark_plan_digest(
    plan: BenchmarkPlan,
) -> str:
    """Return a deterministic digest of resolved benchmark semantics.

    Filesystem storage locations are not identity.  The pipeline is represented
    by its content digest; benchmark specification formatting/location and
    future output directories do not affect the canonical plan identity.
    """

    if not isinstance(plan, BenchmarkPlan):
        raise TypeError(
            "plan must be a BenchmarkPlan"
        )

    document = {
        "pipeline_sha256": _file_sha256(
            plan.pipeline
        ),
        "repeat": plan.repeat,
        "warmup": plan.warmup,
        "variants": [
            {
                "name": variant.name,
                "profile": variant.profile,
                "set": list(variant.set_values),
                "block": list(variant.block_values),
            }
            for variant in plan.variants
        ],
    }

    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def benchmark_plan_record(
    plan: BenchmarkPlan,
    *,
    operation: Operation,
    subject_revision: RevisionRef,
    metadata: Mapping[str, Any] | None = None,
) -> PlanRecord:
    """Wrap one resolved BenchmarkPlan in the canonical planning envelope."""

    if not isinstance(plan, BenchmarkPlan):
        raise TypeError(
            "plan must be a BenchmarkPlan"
        )

    if not isinstance(operation, Operation):
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

    digest = benchmark_plan_digest(plan)

    return PlanRecord(
        plan_id=f"benchmark-{digest[:16]}",
        kind=BENCHMARK_PLAN,
        operation=operation,
        subject_revision=subject_revision,
        payload=plan,
        metadata={
            "benchmark_digest": digest,
            **dict(metadata or {}),
        },
    )


__all__ = [
    "benchmark_plan_digest",
    "benchmark_plan_record",
]
