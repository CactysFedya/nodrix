"""Canonical bridge for Nodrix workflow plans.

The workflow planner remains responsible for domain-specific planning.
This module wraps an already resolved WorkflowPlanResult in the canonical
PlanRecord envelope without changing workflow execution semantics.

The canonical Operation subject is intentionally supplied by the caller.
A workflow is an implementation mechanism for an Operation and is not
necessarily the logical subject of that Operation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .model import (
    WORKFLOW,
    Operation,
    PlanRecord,
    RevisionRef,
)
from .workflow_planning import WorkflowPlanResult


def _digest_payload(plan: WorkflowPlanResult) -> dict[str, Any]:
    """Return the location-independent semantic form of a workflow plan."""

    return {
        "name": plan.name,
        "implements": plan.implements,
        "dry_run": plan.dry_run,
        "force": plan.force,
        "environment": plan.environment,
        "generated": plan.generated,
        "steps": [
            {
                "index": step.index,
                "step_id": step.step_id,
                "recipe": step.recipe,
                "depends_on": list(step.depends_on),
                "command": step.command,
                "cwd": step.cwd,
                "when_json": step.when_json,
                "environment_overrides": [
                    list(item)
                    for item in step.environment_overrides
                ],
                "timeout_seconds": step.timeout_seconds,
                "continue_on_error": step.continue_on_error,
                "cache_enabled": step.cache_enabled,
                "cache_inputs": list(step.cache_inputs),
                "cache_outputs": list(step.cache_outputs),
                "cache_environment": list(step.cache_environment),
            }
            for step in plan.steps
        ],
    }


def workflow_plan_digest(plan: WorkflowPlanResult) -> str:
    """Return a deterministic SHA-256 digest of one resolved workflow plan.

    Filesystem storage locations such as project root, workflow_path and
    cache state_path are intentionally excluded from the digest.
    """

    if not isinstance(plan, WorkflowPlanResult):
        raise TypeError("plan must be a WorkflowPlanResult")

    encoded = json.dumps(
        _digest_payload(plan),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def workflow_plan_record(
    plan: WorkflowPlanResult,
    *,
    operation: Operation,
    subject_revision: RevisionRef,
    metadata: Mapping[str, Any] | None = None,
) -> PlanRecord:
    """Wrap one resolved WorkflowPlanResult in a canonical PlanRecord."""

    if not isinstance(plan, WorkflowPlanResult):
        raise TypeError("plan must be a WorkflowPlanResult")

    if not isinstance(operation, Operation):
        raise TypeError("operation must be an Operation")

    if not isinstance(subject_revision, RevisionRef):
        raise TypeError("subject_revision must be a RevisionRef")

    if subject_revision.entity != operation.subject:
        raise ValueError(
            "subject_revision must reference the operation subject"
        )

    digest = workflow_plan_digest(plan)

    canonical_metadata: dict[str, Any] = {
        "workflow": plan.name,
        "workflow_path": plan.workflow_path,
        "project_root": plan.root,
        "environment": plan.environment,
        "generated": plan.generated,
        "dry_run": plan.dry_run,
        "force": plan.force,
        "plan_sha256": digest,
    }

    if plan.implements is not None:
        canonical_metadata["implements"] = plan.implements

    if metadata is not None:
        if not isinstance(metadata, Mapping):
            raise TypeError("metadata must be a mapping or None")
        canonical_metadata.update(dict(metadata))

    return PlanRecord(
        plan_id=f"workflow-plan-{digest}",
        kind=WORKFLOW,
        operation=operation,
        subject_revision=subject_revision,
        payload=plan,
        metadata=canonical_metadata,
    )


__all__ = [
    "workflow_plan_digest",
    "workflow_plan_record",
]
