"""Read-only planning and cache explainability for Nodrix workflows.

This module intentionally reuses the workflow executor's cache/condition
semantics. Planning never executes build commands and never creates an
operation run directory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import platform
from typing import Any

from .workflow_execution import (
    _cache_hit,
    _cache_spec,
    _cache_state_path,
    _condition_matches,
    _expand_cache_path,
    _step_cache_fingerprint,
    load_workflow,
    project_environment,
)


@dataclass(frozen=True, slots=True)
class WorkflowStepPlan:
    index: int
    step_id: str
    status: str
    recipe: str | None
    depends_on: tuple[str, ...]
    cache: str
    reasons: tuple[str, ...]
    command: str
    cwd: str
    cache_inputs: tuple[str, ...] = ()
    cache_outputs: tuple[str, ...] = ()
    cache_environment: tuple[str, ...] = ()
    fingerprint: str | None = None
    state_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkflowPlanResult:
    name: str
    root: str
    workflow_path: str
    environment: str | None
    generated: bool
    steps: tuple[WorkflowStepPlan, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "root": self.root,
            "workflow_path": self.workflow_path,
            "environment": self.environment,
            "generated": self.generated,
            "steps": [step.as_dict() for step in self.steps],
        }

    def step(self, step_id: str) -> WorkflowStepPlan:
        for item in self.steps:
            if item.step_id == step_id:
                return item
        available = ", ".join(item.step_id for item in self.steps) or "none"
        raise LookupError(f"Unknown workflow step {step_id!r}; available: {available}")


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a string or array")
    return tuple(str(item) for item in value)


def _normalized_machine(value: str) -> str:
    normalized = value.strip().lower()
    return {
        "arm64": "aarch64",
        "amd64": "x86_64",
    }.get(normalized, normalized)


def _platform_condition_matches(condition: Any) -> bool:
    # Return False only when a step is impossible on this host.
    # Command/file/environment conditions are intentionally not checked here.
    if condition in (None, {}, True):
        return True
    if condition is False:
        return False
    if not isinstance(condition, dict):
        return True

    expected_system = condition.get("system")
    if (
        expected_system
        and platform.system().lower() != str(expected_system).lower()
    ):
        return False

    expected_arch = condition.get("architecture")
    if expected_arch:
        values = (
            [expected_arch]
            if isinstance(expected_arch, str)
            else list(expected_arch)
        )
        accepted = {_normalized_machine(str(value)) for value in values}
        actual = _normalized_machine(platform.machine())
        if actual not in accepted:
            return False

    return True


def _cache_state(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, dict) else None


def _missing_outputs(
    root: Path,
    outputs: tuple[str, ...],
    env: dict[str, str],
) -> tuple[str, ...]:
    missing: list[str] = []
    for raw in outputs:
        if not _expand_cache_path(root, raw, env).exists():
            missing.append(raw)
    return tuple(missing)


def plan_workflow(
    name: str,
    *,
    root: str | Path | None = None,
    environment_name: str | None = None,
    force: bool = False,
) -> WorkflowPlanResult:
    """Resolve execution/cache decisions without running any workflow command."""

    workflow, workflow_path, project_root = load_workflow(name, root=root)
    raw_steps = list(workflow.get("steps") or [])
    source_shell = any(
        not isinstance(step, dict)
        or _platform_condition_matches(step.get("when"))
        for step in raw_steps
    )
    env, _, selected_environment = project_environment(
        project_root,
        environment_name=environment_name,
        source_shell=source_shell,
    )
    workflow_env = dict(workflow.get("environment") or {})
    env.update({str(key): str(value) for key, value in workflow_env.items()})
    if selected_environment:
        env["NODRIX_ENVIRONMENT"] = selected_environment

    seen: set[str] = set()
    statuses: dict[str, str] = {}
    planned: list[WorkflowStepPlan] = []

    for index, raw_step in enumerate(list(workflow.get("steps") or []), start=1):
        if not isinstance(raw_step, dict):
            raise ValueError(f"Workflow step {index} must be a mapping")
        step = dict(raw_step)
        step_id = str(step.get("id") or f"step-{index}")
        if step_id in seen:
            raise ValueError(f"Duplicate workflow step id: {step_id}")
        seen.add(step_id)

        command = step.get("run")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(f"Workflow step {step_id!r} must declare run")

        dependencies = _string_list(step.get("depends_on"), f"step {step_id}.depends_on")
        missing_dependencies = [item for item in dependencies if item not in statuses]
        if missing_dependencies:
            rendered = ", ".join(missing_dependencies)
            raise ValueError(
                f"Workflow step {step_id!r} depends on unknown or later step(s): {rendered}"
            )

        recipe = str(step.get("recipe") or "").strip() or None
        cwd = str(step.get("cwd") or ".")
        matches, condition_detail = _condition_matches(
            step.get("when"),
            root=project_root,
            env=env,
        )

        cache_env = dict(env)
        cache_env.update(
            {
                str(key): str(value)
                for key, value in dict(step.get("environment") or {}).items()
            }
        )
        spec = _cache_spec(step)
        inputs = tuple(spec["inputs"]) if spec is not None else ()
        outputs = tuple(spec["outputs"]) if spec is not None else ()
        cache_environment = tuple(spec["environment"]) if spec is not None else ()
        fingerprint: str | None = None
        state_path: Path | None = None

        if not matches:
            status = "skipped"
            cache_status = "skipped"
            reasons = (condition_detail or "condition did not match",)
        else:
            dirty_dependencies = tuple(
                item for item in dependencies if statuses.get(item) == "planned"
            )
            reasons_list: list[str] = []

            if spec is None:
                status = "planned"
                cache_status = "disabled"
                reasons_list.append("cache is disabled for this step")
            else:
                state_path = _cache_state_path(project_root, name, step_id)
                fingerprint = _step_cache_fingerprint(
                    root=project_root,
                    step_id=step_id,
                    command=command,
                    step=step,
                    env=cache_env,
                    selected_environment=selected_environment,
                    spec=spec,
                )
                state = _cache_state(state_path)
                missing_outputs = _missing_outputs(project_root, outputs, cache_env)

                if force:
                    status = "planned"
                    cache_status = "miss"
                    reasons_list.append("--rebuild requested; cache will be ignored")
                elif dirty_dependencies:
                    status = "planned"
                    cache_status = "miss"
                    reasons_list.append(
                        "dependency will rebuild: " + ", ".join(dirty_dependencies)
                    )
                elif state is None:
                    status = "planned"
                    cache_status = "miss"
                    reasons_list.append("no successful cache entry exists")
                elif missing_outputs:
                    status = "planned"
                    cache_status = "miss"
                    reasons_list.append(
                        "cached output is missing: " + ", ".join(missing_outputs)
                    )
                elif _cache_hit(
                    state_path=state_path,
                    fingerprint=fingerprint,
                    root=project_root,
                    spec=spec,
                    env=cache_env,
                ):
                    status = "cached"
                    cache_status = "hit"
                    reasons_list.append(
                        "inputs, command, environment and platform are unchanged"
                    )
                else:
                    status = "planned"
                    cache_status = "miss"
                    if state.get("status") != "succeeded":
                        reasons_list.append("previous cache entry was not successful")
                    elif state.get("fingerprint") != fingerprint:
                        reasons_list.append(
                            "cache fingerprint changed (tracked inputs, command, environment or platform changed)"
                        )
                    else:
                        reasons_list.append("cache entry is not reusable")

            if dirty_dependencies and spec is None:
                reasons_list.append(
                    "dependency will rebuild: " + ", ".join(dirty_dependencies)
                )
            reasons = tuple(reasons_list)

        statuses[step_id] = status
        planned.append(
            WorkflowStepPlan(
                index=index,
                step_id=step_id,
                status=status,
                recipe=recipe,
                depends_on=dependencies,
                cache=cache_status,
                reasons=reasons,
                command=command,
                cwd=cwd,
                cache_inputs=inputs,
                cache_outputs=outputs,
                cache_environment=cache_environment,
                fingerprint=fingerprint,
                state_path=str(state_path) if state_path is not None else None,
            )
        )

    return WorkflowPlanResult(
        name=name,
        root=str(project_root),
        workflow_path=str(workflow_path),
        environment=selected_environment,
        generated=isinstance(workflow.get("generated"), dict),
        steps=tuple(planned),
    )


__all__ = [
    "WorkflowPlanResult",
    "WorkflowStepPlan",
    "plan_workflow",
]
