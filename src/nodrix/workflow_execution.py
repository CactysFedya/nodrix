from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import time
from typing import Any

import yaml

from .workspace import PROJECT_FILE, find_workspace


@dataclass(frozen=True)
class WorkflowStepResult:
    step_id: str
    status: str
    command: str
    returncode: int | None
    duration_seconds: float
    log_path: str
    detail: str = ""


@dataclass(frozen=True)
class WorkflowRunResult:
    name: str
    status: str
    root: str
    workflow_path: str
    run_directory: str
    started_at: str
    finished_at: str
    steps: tuple[WorkflowStepResult, ...]

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "root": self.root,
            "workflow_path": self.workflow_path,
            "run_directory": self.run_directory,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": [asdict(step) for step in self.steps],
        }


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return dict(value)


def _project_root(value: str | Path | None = None) -> Path:
    selected = Path(value or Path.cwd()).expanduser().resolve()
    root = find_workspace(selected)
    if root is None:
        raise LookupError(f"No {PROJECT_FILE} found from {selected}")
    return root


def _declared_document(
    root: Path,
    config: dict[str, Any],
    section: str,
    name: str,
) -> tuple[dict[str, Any], Path]:
    entries = dict(config.get(section) or {})
    raw = entries.get(name)
    if isinstance(raw, dict):
        return dict(raw), root / PROJECT_FILE
    if isinstance(raw, str):
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
        if not path.is_absolute():
            path = root / path
    else:
        path = root / section / f"{name}.yaml"
    path = path.resolve()
    if not path.is_file():
        available = ", ".join(sorted(entries)) or "none"
        raise FileNotFoundError(
            f"{section} entry {name!r} was not found at {path}; "
            f"registered: {available}"
        )
    return _load_yaml(path), path


def list_workflows(
    root: str | Path | None = None,
) -> dict[str, str]:
    project_root = _project_root(root)
    config = _load_yaml(project_root / PROJECT_FILE)
    return {
        str(name): str(path)
        for name, path in dict(config.get("workflows") or {}).items()
    }


def has_workflow(
    root: str | Path,
    name: str,
) -> bool:
    project_root = _project_root(root)
    config = _load_yaml(project_root / PROJECT_FILE)
    entries = dict(config.get("workflows") or {})
    if name in entries:
        return True
    return (project_root / "workflows" / f"{name}.yaml").is_file()


def load_workflow(
    name: str,
    *,
    root: str | Path | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    project_root = _project_root(root)
    config = _load_yaml(project_root / PROJECT_FILE)
    workflow, path = _declared_document(
        project_root,
        config,
        "workflows",
        name,
    )
    schema = str(workflow.get("schema") or "")
    if schema != "nodrix.workflow/v1":
        raise ValueError(
            f"{path} uses unsupported workflow schema {schema!r}; "
            "expected 'nodrix.workflow/v1'"
        )
    steps = workflow.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"{path} must declare a non-empty steps list")
    return workflow, path, project_root


def _active_context(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    name: str | None = None
    state = root / ".nodrix" / "context"
    if state.is_file():
        name = state.read_text(encoding="utf-8").strip() or None
    defaults = dict(config.get("defaults") or {})
    if name is None:
        raw = defaults.get("context")
        name = str(raw) if raw else None
    contexts = dict(config.get("contexts") or {})
    raw_context = contexts.get(name) if name else None
    return dict(raw_context) if isinstance(raw_context, dict) else {}


def _source_environment(
    root: Path,
    base: dict[str, str],
    paths: list[Path],
) -> dict[str, str]:
    if not paths:
        return base
    missing = [path for path in paths if not path.is_file()]
    if missing:
        rendered = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Environment source files not found: {rendered}")
    commands = ["set -a"]
    commands.extend(f"source {shlex.quote(str(path))}" for path in paths)
    commands.append("env -0")
    completed = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-c", "; ".join(commands)],
        cwd=root,
        env=base,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        detail = completed.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Cannot activate project environment: {detail}")
    result = dict(base)
    for item in completed.stdout.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        result[key.decode(errors="replace")] = value.decode(errors="replace")
    return result


def project_environment(
    root: str | Path | None = None,
    *,
    environment_name: str | None = None,
) -> tuple[dict[str, str], dict[str, Any], str | None]:
    project_root = _project_root(root)
    config = _load_yaml(project_root / PROJECT_FILE)
    defaults = dict(config.get("defaults") or {})
    context = _active_context(project_root, config)
    selected = environment_name or context.get("environment") or defaults.get("environment")
    selected_name = str(selected) if selected else None
    profile_value = context.get("profile") or defaults.get("profile")
    profile_name = str(profile_value) if profile_value else None
    environment: dict[str, Any] = {}
    profile_document: dict[str, Any] = {}
    if selected_name:
        environment, _ = _declared_document(
            project_root,
            config,
            "environments",
            selected_name,
        )
    if profile_name:
        profile_document, _ = _declared_document(
            project_root,
            config,
            "profiles",
            profile_name,
        )

    values = {
        "PROJECT_ROOT": str(project_root),
        "HOME": str(Path.home()),
    }
    variables: dict[str, str] = {}
    for source in (
        dict(environment.get("environment") or {}),
        dict(profile_document.get("variables") or {}),
        dict(context.get("variables") or {}),
    ):
        for key, raw_value in source.items():
            value = str(raw_value)
            for token, replacement in {**values, **variables}.items():
                value = value.replace("${" + token + "}", replacement)
            variables[str(key)] = os.path.expandvars(os.path.expanduser(value))

    raw_sources = dict(environment.get("shell") or {}).get("source") or []
    if isinstance(raw_sources, str):
        raw_sources = [raw_sources]
    sources: list[Path] = []
    for raw in raw_sources:
        text = str(raw)
        for token, replacement in {**values, **variables}.items():
            text = text.replace("${" + token + "}", replacement)
        source = Path(os.path.expandvars(os.path.expanduser(text)))
        if not source.is_absolute():
            source = project_root / source
        sources.append(source.resolve())

    base = dict(os.environ)
    base.update(variables)
    base["NODRIX_PROJECT_ROOT"] = str(project_root)
    if selected_name:
        base["NODRIX_ENVIRONMENT"] = selected_name
    if profile_name:
        base["NODRIX_PROFILE"] = profile_name
    context_name = None
    state = project_root / ".nodrix" / "context"
    if state.is_file():
        context_name = state.read_text(encoding="utf-8").strip() or None
    if context_name is None:
        raw_context = defaults.get("context")
        context_name = str(raw_context) if raw_context else None
    if context_name:
        base["NODRIX_CONTEXT"] = context_name
    return _source_environment(project_root, base, sources), environment, selected_name


def _normalized_machine(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "arm64": "aarch64",
        "amd64": "x86_64",
    }
    return aliases.get(normalized, normalized)


def check_project_environment(
    root: str | Path | None = None,
    *,
    environment_name: str | None = None,
) -> list[dict[str, str]]:
    project_root = _project_root(root)
    env, document, selected = project_environment(
        project_root,
        environment_name=environment_name,
    )
    results: list[dict[str, str]] = []
    platform_spec = dict(document.get("platform") or {})
    expected_system = platform_spec.get("system")
    if expected_system:
        expected = str(expected_system).lower()
        actual = platform.system().lower()
        results.append(
            {
                "check": "platform.system",
                "status": "ok" if actual == expected else "error",
                "detail": f"expected={expected} actual={actual}",
            }
        )
    expected_arch = platform_spec.get("architecture")
    if expected_arch:
        expected_values = (
            [expected_arch] if isinstance(expected_arch, str) else list(expected_arch)
        )
        normalized = {_normalized_machine(str(item)) for item in expected_values}
        actual = _normalized_machine(platform.machine())
        results.append(
            {
                "check": "platform.architecture",
                "status": "ok" if actual in normalized else "error",
                "detail": f"expected={sorted(normalized)} actual={actual}",
            }
        )
    for item in document.get("checks") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        if kind == "command":
            command = str(item.get("command") or "")
            executable = shlex.split(command)[0] if command else ""
            ok = bool(executable and shutil.which(executable, path=env.get("PATH")))
            detail = command
        elif kind == "file":
            path = Path(str(item.get("path") or ""))
            if not path.is_absolute():
                path = project_root / path
            ok = path.is_file()
            detail = str(path)
        elif kind == "directory":
            path = Path(str(item.get("path") or ""))
            if not path.is_absolute():
                path = project_root / path
            ok = path.is_dir()
            detail = str(path)
        elif kind == "environment":
            variable = str(item.get("name") or "")
            ok = bool(env.get(variable))
            detail = variable
        else:
            ok = False
            detail = f"unsupported check type: {kind or '<empty>'}"
        results.append(
            {
                "check": kind or "unknown",
                "status": "ok" if ok else "error",
                "detail": detail,
            }
        )
    if selected and not results:
        results.append(
            {
                "check": "environment",
                "status": "ok",
                "detail": selected,
            }
        )
    return results


def _condition_matches(
    condition: Any,
    *,
    root: Path,
    env: dict[str, str],
) -> tuple[bool, str]:
    if condition in (None, {}, True):
        return True, ""
    if condition is False:
        return False, "condition is false"
    if not isinstance(condition, dict):
        raise ValueError("step.when must be a mapping or boolean")

    expected_system = condition.get("system")
    if expected_system and platform.system().lower() != str(expected_system).lower():
        return False, f"system is {platform.system()}"
    expected_arch = condition.get("architecture")
    if expected_arch:
        values = [expected_arch] if isinstance(expected_arch, str) else expected_arch
        accepted = {_normalized_machine(str(value)) for value in values}
        actual = _normalized_machine(platform.machine())
        if actual not in accepted:
            return False, f"architecture is {actual}"
    command = condition.get("command_exists")
    if command and shutil.which(str(command), path=env.get("PATH")) is None:
        return False, f"command not found: {command}"
    file_name = condition.get("file_exists")
    if file_name:
        path = Path(str(file_name))
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            return False, f"file not found: {path}"
    variable = condition.get("environment")
    if variable and not env.get(str(variable)):
        return False, f"environment variable is not set: {variable}"
    return True, ""


def _step_cwd(root: Path, value: Any) -> Path:
    path = Path(str(value or ".")).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Workflow cwd escapes the project root: {resolved}") from exc
    if not resolved.is_dir():
        raise FileNotFoundError(f"Workflow cwd does not exist: {resolved}")
    return resolved


def _shell_command(command: str) -> list[str]:
    bash = shutil.which("bash")
    if bash:
        return [bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", command]
    if os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", command]
    shell = os.environ.get("SHELL") or "/bin/sh"
    return [shell, "-e", "-c", command]


def run_workflow(
    name: str,
    *,
    root: str | Path | None = None,
    environment_name: str | None = None,
    dry_run: bool = False,
) -> WorkflowRunResult:
    workflow, workflow_path, project_root = load_workflow(name, root=root)
    env, _, selected_environment = project_environment(
        project_root,
        environment_name=environment_name,
    )
    workflow_env = dict(workflow.get("environment") or {})
    env.update({str(key): str(value) for key, value in workflow_env.items()})
    if selected_environment:
        env["NODRIX_ENVIRONMENT"] = selected_environment

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
    safe_name = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in name
    ).strip("-") or "workflow"
    run_directory = project_root / ".nodrix" / "operations" / f"{stamp}-{safe_name}"
    logs_directory = run_directory / "logs"
    logs_directory.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    step_results: list[WorkflowStepResult] = []
    failed = False
    steps = list(workflow.get("steps") or [])
    for index, raw_step in enumerate(steps, start=1):
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
        log_path = logs_directory / f"{index:02d}-{step_id}.log"
        matches, detail = _condition_matches(
            step.get("when"),
            root=project_root,
            env=env,
        )
        if not matches:
            log_path.write_text(f"SKIPPED: {detail}\n", encoding="utf-8")
            step_results.append(
                WorkflowStepResult(
                    step_id=step_id,
                    status="skipped",
                    command=command,
                    returncode=None,
                    duration_seconds=0.0,
                    log_path=str(log_path),
                    detail=detail,
                )
            )
            continue
        if dry_run:
            log_path.write_text(command + "\n", encoding="utf-8")
            step_results.append(
                WorkflowStepResult(
                    step_id=step_id,
                    status="planned",
                    command=command,
                    returncode=None,
                    duration_seconds=0.0,
                    log_path=str(log_path),
                )
            )
            continue

        cwd = _step_cwd(project_root, step.get("cwd"))
        step_env = dict(env)
        step_env.update(
            {
                str(key): str(value)
                for key, value in dict(step.get("environment") or {}).items()
            }
        )
        timeout_value = step.get("timeout_seconds")
        timeout = float(timeout_value) if timeout_value is not None else None
        started = time.monotonic()
        try:
            completed = subprocess.run(
                _shell_command(command),
                cwd=cwd,
                env=step_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.monotonic() - started
            output = completed.stdout
            if completed.stderr:
                output += ("\n" if output else "") + completed.stderr
            log_path.write_text(output, encoding="utf-8")
            status = "succeeded" if completed.returncode == 0 else "failed"
            result = WorkflowStepResult(
                step_id=step_id,
                status=status,
                command=command,
                returncode=completed.returncode,
                duration_seconds=duration,
                log_path=str(log_path),
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            output = str(stdout)
            if stderr:
                output += ("\n" if output else "") + str(stderr)
            output += f"\nTimed out after {timeout} seconds\n"
            log_path.write_text(output, encoding="utf-8")
            result = WorkflowStepResult(
                step_id=step_id,
                status="failed",
                command=command,
                returncode=None,
                duration_seconds=duration,
                log_path=str(log_path),
                detail=f"timeout after {timeout} seconds",
            )
        step_results.append(result)
        if result.status == "failed":
            failed = True
            if not bool(step.get("continue_on_error", False)):
                break

    finished = datetime.now(timezone.utc)
    status = "planned" if dry_run else "failed" if failed else "succeeded"
    result = WorkflowRunResult(
        name=name,
        status=status,
        root=str(project_root),
        workflow_path=str(workflow_path),
        run_directory=str(run_directory),
        started_at=now.isoformat(),
        finished_at=finished.isoformat(),
        steps=tuple(step_results),
    )
    summary = run_directory / "summary.json"
    summary.write_text(
        json.dumps(result.as_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return result
