from __future__ import annotations

import json
import os
from pathlib import Path

from nodrix.workflow_execution import (
    execute_workflow_plan,
)
from nodrix.workflow_planning import (
    WorkflowPlanResult,
    WorkflowStepPlan,
)


def _environment(
    root: Path,
) -> tuple[tuple[str, str], ...]:
    env = dict(os.environ)
    env["NODRIX_PROJECT_ROOT"] = str(root)
    return tuple(sorted(env.items()))


def _plan(
    root: Path,
    *,
    steps: tuple[WorkflowStepPlan, ...],
) -> WorkflowPlanResult:
    return WorkflowPlanResult(
        name="exact",
        root=str(root),
        workflow_path=str(
            root / "workflow.yaml"
        ),
        environment=None,
        generated=False,
        steps=steps,
        execution_environment=_environment(
            root
        ),
    )


def test_exact_execution_does_not_reload_workflow_definition(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        "this file is intentionally not executable\n",
        encoding="utf-8",
    )

    plan = _plan(
        tmp_path,
        steps=(
            WorkflowStepPlan(
                index=1,
                step_id="write",
                status="planned",
                recipe=None,
                depends_on=(),
                cache="disabled",
                reasons=(),
                command=(
                    "python3 -c "
                    "\"from pathlib import Path; "
                    "Path('result.txt').write_text('planned')\""
                ),
                cwd=".",
            ),
        ),
    )

    result = execute_workflow_plan(
        plan
    )

    assert result.succeeded
    assert (
        tmp_path / "result.txt"
    ).read_text(
        encoding="utf-8"
    ) == "planned"


def test_execution_rechecks_cache_instead_of_trusting_plan_preview(
    tmp_path: Path,
) -> None:
    plan = _plan(
        tmp_path,
        steps=(
            WorkflowStepPlan(
                index=1,
                step_id="build",
                status="cached",
                recipe=None,
                depends_on=(),
                cache="hit",
                reasons=(
                    "plan-time cache hit",
                ),
                command=(
                    "python3 -c "
                    "\"from pathlib import Path; "
                    "Path('output.txt').write_text('executed')\""
                ),
                cwd=".",
                cache_inputs=(),
                cache_outputs=(
                    "output.txt",
                ),
                cache_environment=(),
                fingerprint="plan-time-value",
                cache_enabled=True,
            ),
        ),
    )

    result = execute_workflow_plan(
        plan
    )

    assert result.succeeded
    assert result.steps[0].status == "succeeded"
    assert (
        tmp_path / "output.txt"
    ).read_text(
        encoding="utf-8"
    ) == "executed"


def test_execution_rechecks_runtime_condition(
    tmp_path: Path,
) -> None:
    condition = {
        "file_exists": "ready.flag"
    }

    plan = _plan(
        tmp_path,
        steps=(
            WorkflowStepPlan(
                index=1,
                step_id="conditional",
                status="skipped",
                recipe=None,
                depends_on=(),
                cache="skipped",
                reasons=(
                    "file did not exist while planning",
                ),
                command=(
                    "python3 -c "
                    "\"from pathlib import Path; "
                    "Path('ran.txt').write_text('yes')\""
                ),
                cwd=".",
                when_json=json.dumps(
                    condition,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        ),
    )

    (
        tmp_path / "ready.flag"
    ).write_text(
        "ready",
        encoding="utf-8",
    )

    result = execute_workflow_plan(
        plan
    )

    assert result.succeeded
    assert result.steps[0].status == "succeeded"
    assert (
        tmp_path / "ran.txt"
    ).is_file()


def test_exact_plan_carries_step_environment_and_failure_policy(
    tmp_path: Path,
) -> None:
    plan = _plan(
        tmp_path,
        steps=(
            WorkflowStepPlan(
                index=1,
                step_id="fail",
                status="planned",
                recipe=None,
                depends_on=(),
                cache="disabled",
                reasons=(),
                command="exit 7",
                cwd=".",
                continue_on_error=True,
            ),
            WorkflowStepPlan(
                index=2,
                step_id="environment",
                status="planned",
                recipe=None,
                depends_on=(),
                cache="disabled",
                reasons=(),
                command=(
                    "python3 -c "
                    "\"import os; "
                    "from pathlib import Path; "
                    "Path('env.txt').write_text(os.environ['EXACT_VALUE'])\""
                ),
                cwd=".",
                environment_overrides=(
                    ("EXACT_VALUE", "from-plan"),
                ),
            ),
        ),
    )

    result = execute_workflow_plan(
        plan
    )

    assert not result.succeeded
    assert [
        step.status
        for step in result.steps
    ] == [
        "failed",
        "succeeded",
    ]

    assert (
        tmp_path / "env.txt"
    ).read_text(
        encoding="utf-8"
    ) == "from-plan"
