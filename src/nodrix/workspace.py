from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from typing import Any

import yaml

from .storage_layout import StorageLayout


PROJECT_FILE = "nodrix.yaml"


@dataclass(frozen=True)
class WorkspaceResolution:
    root: Path
    config_path: Path | None
    config: dict[str, Any]
    pipeline: Path
    pipeline_name: str
    context_name: str | None
    environment_name: str | None
    profile_name: str | None
    view: str
    runtime_profile: str | None
    variables: dict[str, str]
    sources: tuple[Path, ...]
    checks: tuple[dict[str, Any], ...]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return dict(value)


def find_workspace(
    start: str | Path | None = None,
    *,
    required: bool = False,
) -> Path | None:
    path = Path(start or Path.cwd()).expanduser().resolve()
    if path.is_file():
        path = path.parent
    for candidate in (path, *path.parents):
        if (candidate / PROJECT_FILE).is_file():
            return candidate
    if required:
        raise LookupError(
            f"No {PROJECT_FILE} found from {path} or its parents"
        )
    return None


def resolve_project_root(value: str | Path | None = None) -> Path:
    selected = Path(
        value or Path.cwd()
    ).expanduser().resolve()

    if StorageLayout(
        selected
    ).runs_root.exists():
        return selected

    return find_workspace(
        selected
    ) or selected


def _active_context(root: Path, config: dict[str, Any]) -> str | None:
    state = StorageLayout(
        root
    ).context_file

    if state.is_file():
        selected = state.read_text(encoding="utf-8").strip()
        if selected:
            return selected
    value = _mapping(config.get("defaults")).get("context")
    return str(value) if value else None


def set_active_context(root: Path, name: str) -> Path:
    config = _load_yaml(root / PROJECT_FILE)
    contexts = _mapping(config.get("contexts"))
    if name not in contexts:
        available = ", ".join(sorted(contexts)) or "none"
        raise KeyError(f"Unknown context {name!r}; available: {available}")
    target = StorageLayout(
        root
    ).context_file

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    target.write_text(name + "\n", encoding="utf-8")
    return target


def _expand(value: Any, values: dict[str, str]) -> str:
    text = str(value)
    for key, replacement in values.items():
        text = text.replace("${" + key + "}", replacement)
    return os.path.expandvars(os.path.expanduser(text))


def _load_named_document(
    root: Path,
    section: str,
    name: str | None,
) -> dict[str, Any]:
    if not name:
        return {}
    config = _load_yaml(root / PROJECT_FILE)
    declared = _mapping(config.get(section))
    raw = declared.get(name)
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        path = Path(_expand(raw, {"PROJECT_ROOT": str(root)}))
        if not path.is_absolute():
            path = root / path
        return _load_yaml(path.resolve())
    singular = section[:-1] if section.endswith("s") else section
    for directory in (section, singular):
        path = root / directory / f"{name}.yaml"
        if path.is_file():
            return _load_yaml(path)
    raise FileNotFoundError(
        f"{section} entry {name!r} is not declared and no YAML file exists"
    )


def _direct_pipeline(value: str, cwd: Path) -> Path | None:
    candidate = Path(value).expanduser()
    looks_like_path = (
        candidate.suffix in {".yaml", ".yml"}
        or candidate.is_absolute()
        or "/" in value
        or "\\" in value
        or value.startswith(".")
    )
    if not candidate.is_absolute():
        candidate = cwd / candidate
    if candidate.is_file() or looks_like_path:
        return candidate.resolve()
    return None


def resolve_pipeline_reference(
    reference: str | Path | None = None,
    *,
    start: str | Path | None = None,
) -> WorkspaceResolution:
    cwd = Path(start or Path.cwd()).expanduser().resolve()
    root = find_workspace(cwd)

    direct_reference = (
        _direct_pipeline(str(reference), cwd)
        if reference is not None
        else None
    )
    if direct_reference is not None and direct_reference.is_file():
        config_path = (root / PROJECT_FILE) if root is not None else None
        config = _load_yaml(config_path) if config_path is not None else {}
        defaults = _mapping(config.get("defaults"))
        return WorkspaceResolution(
            root=root or cwd,
            config_path=config_path,
            config=config,
            pipeline=direct_reference,
            pipeline_name=direct_reference.stem,
            context_name=None,
            environment_name=None,
            profile_name=None,
            view=str(defaults.get("view") or "compact"),
            runtime_profile=None,
            variables={},
            sources=(),
            checks=(),
        )

    if root is None:
        raw = str(reference) if reference is not None else "pipeline.yaml"
        pipeline = _direct_pipeline(raw, cwd) or (cwd / raw).resolve()
        if not pipeline.is_file():
            raise FileNotFoundError(f"Pipeline manifest not found: {pipeline}")
        return WorkspaceResolution(
            root=cwd,
            config_path=None,
            config={},
            pipeline=pipeline,
            pipeline_name=pipeline.stem,
            context_name=None,
            environment_name=None,
            profile_name=None,
            view="compact",
            runtime_profile=None,
            variables={},
            sources=(),
            checks=(),
        )

    config_path = root / PROJECT_FILE
    config = _load_yaml(config_path)
    defaults = _mapping(config.get("defaults"))
    pipelines = _mapping(config.get("pipelines"))

    selected = (
        str(reference)
        if reference is not None
        else str(defaults.get("pipeline") or "")
    )
    if not selected:
        raise ValueError(
            "No pipeline was supplied and defaults.pipeline is not set"
        )

    direct = _direct_pipeline(selected, cwd)
    pipeline_name = Path(selected).stem
    if direct is not None and direct.is_file():
        pipeline = direct
    elif selected in pipelines:
        raw = pipelines[selected]
        if isinstance(raw, dict):
            raw = raw.get("path")
        if not raw:
            raise ValueError(f"Pipeline alias {selected!r} has no path")
        values = {
            "PROJECT_ROOT": str(root),
            "HOME": str(Path.home()),
        }
        pipeline = Path(_expand(raw, values))
        if not pipeline.is_absolute():
            pipeline = root / pipeline
        pipeline = pipeline.resolve()
        pipeline_name = selected
    else:
        pipeline = (root / "pipelines" / f"{selected}.yaml").resolve()
        pipeline_name = selected

    if not pipeline.is_file():
        available = ", ".join(sorted(pipelines)) or "none"
        raise FileNotFoundError(
            f"Pipeline {selected!r} was not found at {pipeline}; "
            f"workspace aliases: {available}"
        )

    context_name = _active_context(root, config)
    contexts = _mapping(config.get("contexts"))
    context = _mapping(contexts.get(context_name)) if context_name else {}

    environment_name = context.get("environment") or defaults.get("environment")
    profile_name = context.get("profile") or defaults.get("profile")
    environment_name = str(environment_name) if environment_name else None
    profile_name = str(profile_name) if profile_name else None

    environment = _load_named_document(
        root,
        "environments",
        environment_name,
    )
    profile = _load_named_document(root, "profiles", profile_name)

    values = {
        "PROJECT_ROOT": str(root),
        "HOME": str(Path.home()),
    }
    variables: dict[str, str] = {}
    for source in (
        _mapping(environment.get("environment")),
        _mapping(profile.get("variables")),
        _mapping(context.get("variables")),
    ):
        for key, value in source.items():
            merged = {**values, **variables}
            variables[str(key)] = _expand(value, merged)

    source_items = (
        _mapping(environment.get("shell")).get("source")
        or environment.get("source")
        or ()
    )
    if isinstance(source_items, str):
        source_items = [source_items]
    sources: list[Path] = []
    for raw in source_items:
        path = Path(_expand(raw, {**values, **variables}))
        if not path.is_absolute():
            path = root / path
        sources.append(path.resolve())

    runtime_profile = (
        context.get("runtime_profile")
        or profile.get("runtime_profile")
        or defaults.get("runtime_profile")
    )
    view = str(
        context.get("view")
        or defaults.get("view")
        or "compact"
    )
    checks = environment.get("checks")
    if checks is None:
        checks = []
    if not isinstance(checks, list):
        raise ValueError("environment checks must be a list")

    return WorkspaceResolution(
        root=root,
        config_path=config_path,
        config=config,
        pipeline=pipeline,
        pipeline_name=pipeline_name,
        context_name=context_name,
        environment_name=environment_name,
        profile_name=profile_name,
        view=view,
        runtime_profile=str(runtime_profile) if runtime_profile else None,
        variables=variables,
        sources=tuple(sources),
        checks=tuple(dict(item) for item in checks if isinstance(item, dict)),
    )


def build_environment(
    resolution: WorkspaceResolution,
) -> dict[str, str]:
    env = dict(os.environ)
    env.update(resolution.variables)
    env["NODRIX_PROJECT_ROOT"] = str(resolution.root)
    env["NODRIX_PIPELINE"] = str(resolution.pipeline)
    if resolution.context_name:
        env["NODRIX_CONTEXT"] = resolution.context_name

    missing = [path for path in resolution.sources if not path.is_file()]
    if missing:
        rendered = ", ".join(str(item) for item in missing)
        raise FileNotFoundError(f"Environment source files not found: {rendered}")

    if resolution.sources:
        commands = ["set -a"]
        commands.extend(
            f"source {shlex.quote(str(path))}"
            for path in resolution.sources
        )
        commands.append("env -0")
        completed = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", "; ".join(commands)],
            cwd=resolution.root,
            env=env,
            check=False,
            capture_output=True,
        )
        if completed.returncode:
            error = completed.stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"Cannot activate workspace environment: {error}"
            )
        captured: dict[str, str] = {}
        for item in completed.stdout.split(b"\0"):
            if not item or b"=" not in item:
                continue
            key, value = item.split(b"=", 1)
            captured[key.decode(errors="replace")] = value.decode(
                errors="replace"
            )
        env.update(captured)

    env.update(resolution.variables)
    env["NODRIX_PROJECT_ROOT"] = str(resolution.root)
    env["NODRIX_PIPELINE"] = str(resolution.pipeline)
    if resolution.context_name:
        env["NODRIX_CONTEXT"] = resolution.context_name
    return env


def activate_workspace_environment(
    resolution: WorkspaceResolution,
) -> dict[str, str]:
    env = build_environment(resolution)
    os.environ.clear()
    os.environ.update(env)
    return env


def export_environment(resolution: WorkspaceResolution) -> str:
    lines = [
        f"source {shlex.quote(str(path))}"
        for path in resolution.sources
    ]
    variables = {
        **resolution.variables,
        "NODRIX_PROJECT_ROOT": str(resolution.root),
        "NODRIX_PIPELINE": str(resolution.pipeline),
    }
    if resolution.context_name:
        variables["NODRIX_CONTEXT"] = resolution.context_name
    lines.extend(
        f"export {key}={shlex.quote(value)}"
        for key, value in sorted(variables.items())
    )
    return "\n".join(lines) + ("\n" if lines else "")


def check_environment(
    resolution: WorkspaceResolution,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for path in resolution.sources:
        results.append(
            {
                "check": f"source {path}",
                "status": "ok" if path.is_file() else "error",
                "detail": str(path),
            }
        )
    env = {**os.environ, **resolution.variables}
    for item in resolution.checks:
        kind = str(item.get("type", "")).strip()
        if kind == "file":
            path = Path(_expand(item.get("path", ""), env))
            ok = path.is_file()
            detail = str(path)
        elif kind == "directory":
            path = Path(_expand(item.get("path", ""), env))
            ok = path.is_dir()
            detail = str(path)
        elif kind == "command":
            command = str(item.get("command", "")).strip()
            executable = shlex.split(command)[0] if command else ""
            ok = bool(executable and shutil.which(executable, path=env.get("PATH")))
            detail = command
        elif kind == "environment":
            name = str(item.get("name", "")).strip()
            ok = bool(env.get(name))
            detail = name
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
    return results


def default_view(start: str | Path | None = None) -> str:
    root = find_workspace(start)
    if root is None:
        return "compact"
    config = _load_yaml(root / PROJECT_FILE)
    defaults = _mapping(config.get("defaults"))
    context_name = _active_context(root, config)
    contexts = _mapping(config.get("contexts"))
    context = _mapping(contexts.get(context_name)) if context_name else {}
    return str(context.get("view") or defaults.get("view") or "compact")


def create_workspace(directory: Path, *, force: bool = False) -> list[Path]:
    root = directory.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    project_file = root / PROJECT_FILE
    if project_file.exists() and not force:
        raise FileExistsError(f"{project_file} already exists")

    for relative in (
        "pipelines",
        "configs",
        "environments",
        "profiles",
        "views",
        "tests",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)

    project = {
        "schema": "nodrix.project/v1",
        "name": root.name,
        "defaults": {
            "pipeline": "main",
            "context": "local",
            "view": "compact",
        },
        "pipelines": {"main": "pipelines/main.yaml"},
        "contexts": {
            "local": {
                "environment": "local",
                "profile": "default",
            }
        },
        "environments": {"local": "environments/local.yaml"},
        "profiles": {"default": "profiles/default.yaml"},
    }
    environment = {
        "schema": "nodrix.environment/v1",
        "name": "local",
        "shell": {"source": []},
        "environment": {},
        "checks": [],
    }
    profile = {
        "schema": "nodrix.profile/v1",
        "name": "default",
        "variables": {},
    }
    view = {
        "schema": "nodrix.view/v1",
        "name": "compact",
        "style": {"borders": "none", "spacing": "compact"},
    }

    project_file.write_text(
        yaml.safe_dump(project, sort_keys=False),
        encoding="utf-8",
    )
    (root / "environments/local.yaml").write_text(
        yaml.safe_dump(environment, sort_keys=False),
        encoding="utf-8",
    )
    (root / "profiles/default.yaml").write_text(
        yaml.safe_dump(profile, sort_keys=False),
        encoding="utf-8",
    )
    (root / "views/compact.yaml").write_text(
        yaml.safe_dump(view, sort_keys=False),
        encoding="utf-8",
    )
    readme = root / "pipelines/README.md"
    readme.write_text(
        "Place pipeline manifests here and register aliases in nodrix.yaml.\n",
        encoding="utf-8",
    )
    return [
        project_file,
        root / "environments/local.yaml",
        root / "profiles/default.yaml",
        root / "views/compact.yaml",
        readme,
    ]


def supervisor_state(root: Path) -> Path:
    return StorageLayout(
        root
    ).supervisor_file


def read_supervisor(root: Path) -> dict[str, Any]:
    path = supervisor_state(root)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}
