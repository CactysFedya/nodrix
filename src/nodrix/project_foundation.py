from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import yaml

from .workspace import PROJECT_FILE, find_workspace


_RESOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RESOURCE_SECTIONS = {
    "system": ("systems", "systems"),
    "pipeline": ("pipelines", "pipelines"),
    "workflow": ("workflows", "workflows"),
    "environment": ("environments", "environments"),
    "profile": ("profiles", "profiles"),
    "component": ("components", "components"),
}


@dataclass(frozen=True)
class ProjectResource:
    kind: str
    name: str
    path: Path
    project_file: Path


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return dict(value)


def _atomic_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            yaml.safe_dump(value, stream, sort_keys=False)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _project_root(value: str | Path | None = None) -> Path:
    selected = Path(value or Path.cwd()).expanduser().resolve()
    root = find_workspace(selected)
    if root is None:
        if (selected / PROJECT_FILE).is_file():
            return selected
        raise LookupError(f"No {PROJECT_FILE} found from {selected}")
    return root


def _append_gitignore(path: Path, entries: tuple[str, ...]) -> None:
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = existing.splitlines()
    known = set(lines)
    changed = False
    for entry in entries:
        if entry not in known:
            lines.append(entry)
            known.add(entry)
            changed = True
    if changed or not path.exists():
        text = "\n".join(lines).rstrip() + "\n"
        path.write_text(text, encoding="utf-8")


def create_progressive_project(
    directory: str | Path,
    *,
    force: bool = False,
) -> list[Path]:
    """Create only the project manifest and local ignore rules.

    Resource directories are created later by :func:`add_project_resource`.
    Existing source repositories are supported: only an existing project
    manifest is considered a conflict.
    """

    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    project_file = root / PROJECT_FILE
    if project_file.exists() and not force:
        raise FileExistsError(f"{project_file} already exists")

    project = {
        "schema": "nodrix.project/v1",
        "name": root.name.replace(" ", "-").lower(),
        "defaults": {"view": "compact"},
        "systems": {},
        "pipelines": {},
        "workflows": {},
        "components": {},
        "contexts": {},
        "environments": {},
        "profiles": {},
    }
    _atomic_yaml(project_file, project)
    gitignore = root / ".gitignore"
    _append_gitignore(
        gitignore,
        (
            ".nodrix/",
            ".venv/",
            "__pycache__/",
            "*.py[cod]",
        ),
    )
    return [project_file, gitignore]


def _pipeline_document(name: str) -> dict[str, Any]:
    return {
        "apiVersion": "plyctl.dev/v2",
        "kind": "Pipeline",
        "metadata": {"name": name},
        "runtime": {
            "mode": "offline",
            "engine": "unified",
            "type_validation": "first",
        },
        "nodes": {},
        "edges": [],
        "fragments": {},
        "recording": {},
        "security": {},
        "placement": {},
        "streams": {"exports": []},
    }


def _system_document(name: str) -> dict[str, Any]:
    """Create the smallest canonical System document.

    System details are added progressively; the generated file is already a
    valid ``nodrix.system/v1`` document and can immediately be validated or
    planned.
    """

    return {
        "apiVersion": "nodrix.system/v1",
        "kind": "System",
        "name": name,
    }


def _workflow_document(name: str, template: str | None) -> dict[str, Any]:
    selected = (template or "empty").lower()
    commands: dict[str, str] = {
        "empty": f'echo "Configure the {name} workflow in workflows/{name}.yaml"',
        "python-build": "python3 -m build",
        "python-test": "python3 -m pytest -q",
        "python-install": "python3 -m pip install -e . --no-build-isolation",
        "cmake-build": (
            "cmake -S . -B build -DCMAKE_BUILD_TYPE=Release\n"
            "cmake --build build --parallel"
        ),
        "colcon-build": "colcon build --symlink-install",
    }
    if selected not in commands:
        available = ", ".join(sorted(commands))
        raise ValueError(
            f"Unknown workflow template {selected!r}; choose: {available}"
        )
    return {
        "schema": "nodrix.workflow/v1",
        "name": name,
        "steps": [
            {
                "id": name,
                "run": commands[selected],
            }
        ],
    }


def _environment_document(name: str, template: str | None) -> dict[str, Any]:
    selected = (template or "empty").lower()
    if selected == "empty":
        return {
            "schema": "nodrix.environment/v1",
            "name": name,
            "shell": {"source": []},
            "environment": {},
            "checks": [],
        }
    if selected == "raspberry-pi5":
        return {
            "schema": "nodrix.environment/v1",
            "name": name,
            "platform": {
                "system": "linux",
                "architecture": ["aarch64", "arm64"],
            },
            "shell": {"source": []},
            "environment": {
                "NODRIX_TARGET": "raspberry-pi5",
                "CMAKE_BUILD_PARALLEL_LEVEL": "4",
            },
            "checks": [
                {"type": "command", "command": "python3"},
                {"type": "command", "command": "cmake"},
            ],
        }
    raise ValueError(
        f"Unknown environment template {selected!r}; "
        "choose: empty, raspberry-pi5"
    )


def _profile_document(name: str) -> dict[str, Any]:
    return {
        "schema": "nodrix.profile/v1",
        "name": name,
        "variables": {},
    }


def _component_document(name: str) -> dict[str, Any]:
    return {
        "schema": "nodrix.component/v1",
        "name": name,
        "lifecycle": "managed",
        "provider": "process",
        "configuration": {},
    }


def _resource_document(
    kind: str,
    name: str,
    template: str | None,
) -> dict[str, Any]:
    if kind == "system":
        if template not in {None, "empty"}:
            raise ValueError("System currently supports only the empty template")
        return _system_document(name)
    if kind == "pipeline":
        if template not in {None, "empty"}:
            raise ValueError("Pipeline currently supports only the empty template")
        return _pipeline_document(name)
    if kind == "workflow":
        return _workflow_document(name, template)
    if kind == "environment":
        return _environment_document(name, template)
    if kind == "profile":
        if template not in {None, "empty"}:
            raise ValueError("Profile currently supports only the empty template")
        return _profile_document(name)
    if kind == "component":
        if template not in {None, "empty"}:
            raise ValueError("Component currently supports only the empty template")
        return _component_document(name)
    available = ", ".join(sorted(_RESOURCE_SECTIONS))
    raise ValueError(f"Unknown resource kind {kind!r}; choose: {available}")


def add_project_resource(
    kind: str,
    name: str,
    *,
    root: str | Path | None = None,
    template: str | None = None,
    force: bool = False,
    make_default: bool = False,
) -> ProjectResource:
    normalized_kind = kind.strip().lower().replace("_", "-")
    normalized_name = name.strip()
    if normalized_kind not in _RESOURCE_SECTIONS:
        available = ", ".join(sorted(_RESOURCE_SECTIONS))
        raise ValueError(
            f"Unknown resource kind {normalized_kind!r}; choose: {available}"
        )
    if not _RESOURCE_NAME.fullmatch(normalized_name):
        raise ValueError(
            "Resource name must start with an alphanumeric character and "
            "contain only letters, digits, '.', '_' or '-'"
        )

    project_root = _project_root(root)
    project_file = project_root / PROJECT_FILE
    config = _load_yaml(project_file)
    section, directory_name = _RESOURCE_SECTIONS[normalized_kind]
    entries = dict(config.get(section) or {})
    relative = Path(directory_name) / f"{normalized_name}.yaml"
    target = project_root / relative

    if normalized_name in entries and not force:
        raise FileExistsError(
            f"{normalized_kind} {normalized_name!r} is already registered"
        )
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists")

    if make_default and normalized_kind not in {
        "system",
        "pipeline",
        "environment",
        "profile",
    }:
        raise ValueError(
            "--default is supported for system, pipeline, environment and profile"
        )

    document = _resource_document(normalized_kind, normalized_name, template)
    _atomic_yaml(target, document)
    entries[normalized_name] = relative.as_posix()
    config[section] = entries

    if make_default:
        defaults = dict(config.get("defaults") or {})
        defaults[normalized_kind] = normalized_name
        config["defaults"] = defaults

    _atomic_yaml(project_file, config)
    return ProjectResource(
        kind=normalized_kind,
        name=normalized_name,
        path=target,
        project_file=project_file,
    )


def list_project_resources(
    kind: str | None = None,
    *,
    root: str | Path | None = None,
) -> dict[str, dict[str, str]]:
    project_root = _project_root(root)
    config = _load_yaml(project_root / PROJECT_FILE)
    if kind is not None:
        normalized = kind.strip().lower().replace("_", "-")
        if normalized not in _RESOURCE_SECTIONS:
            available = ", ".join(sorted(_RESOURCE_SECTIONS))
            raise ValueError(f"Unknown resource kind {normalized!r}; choose: {available}")
        section = _RESOURCE_SECTIONS[normalized][0]
        return {normalized: dict(config.get(section) or {})}
    return {
        resource_kind: dict(config.get(section) or {})
        for resource_kind, (section, _) in _RESOURCE_SECTIONS.items()
    }

def resolve_project_resource(
    kind: str,
    name: str | None = None,
    *,
    root: str | Path | None = None,
) -> ProjectResource:
    """Resolve a registered resource by explicit name or project default.

    When no explicit/default name exists, a section containing exactly one
    resource resolves automatically.  Multiple resources remain explicit so a
    command never guesses which System/Pipeline the user meant.
    """

    normalized_kind = kind.strip().lower().replace("_", "-")
    if normalized_kind not in _RESOURCE_SECTIONS:
        available = ", ".join(sorted(_RESOURCE_SECTIONS))
        raise ValueError(
            f"Unknown resource kind {normalized_kind!r}; choose: {available}"
        )

    project_root = _project_root(root)
    project_file = project_root / PROJECT_FILE
    config = _load_yaml(project_file)
    section, _ = _RESOURCE_SECTIONS[normalized_kind]
    entries = dict(config.get(section) or {})

    selected = name.strip() if name is not None else ""
    if not selected:
        default = dict(config.get("defaults") or {}).get(normalized_kind)
        selected = str(default).strip() if default else ""
    if not selected and len(entries) == 1:
        selected = str(next(iter(entries)))
    if not selected:
        if not entries:
            raise LookupError(
                f"No {normalized_kind} is registered in {project_file}; "
                f"add one with 'plyctl project add {normalized_kind} NAME'"
            )
        available = ", ".join(sorted(str(item) for item in entries))
        raise LookupError(
            f"No default {normalized_kind} is selected; available: {available}. "
            f"Use --default when adding one or pass an explicit path/name."
        )

    raw = entries.get(selected)
    if raw is None:
        available = ", ".join(sorted(str(item) for item in entries)) or "none"
        raise LookupError(
            f"Unknown {normalized_kind} {selected!r}; registered: {available}"
        )
    if not isinstance(raw, str):
        raise ValueError(
            f"Project {section}.{selected} must be a path string, got "
            f"{type(raw).__name__}"
        )

    target = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not target.is_absolute():
        target = project_root / target
    target = target.resolve()
    if not target.is_file():
        raise FileNotFoundError(
            f"Registered {normalized_kind} {selected!r} does not exist: {target}"
        )
    return ProjectResource(
        kind=normalized_kind,
        name=selected,
        path=target,
        project_file=project_file,
    )
