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

_AUTHORING_LANGUAGES = frozenset({
    "en",
    "ru",
})


def _normalize_authoring_language(
    value: str | None,
) -> str:
    language = (
        str(value or "en")
        .strip()
        .lower()
    )

    if language not in _AUTHORING_LANGUAGES:
        available = ", ".join(
            sorted(
                _AUTHORING_LANGUAGES
            )
        )
        raise ValueError(
            f"Unknown project language {language!r}; "
            f"choose: {available}"
        )

    return language


def _project_authoring_language(
    config: dict[str, Any],
) -> str:
    defaults = dict(
        config.get("defaults")
        or {}
    )

    return _normalize_authoring_language(
        defaults.get("language")
    )
_RESOURCE_SECTIONS = {
    "system": ("systems", "systems"),
    "pipeline": ("pipelines", "pipelines"),
    "workflow": ("workflows", "workflows"),
    "environment": ("environments", "environments"),
    "profile": ("profiles", "profiles"),
    # Compatibility-only registration used by existing project manifests.
    # Local SDK source modules live in components/*.py and are not project
    # resources of kind Component.
    "component": ("components", "components"),
}

# Preferred resource kinds for new project authoring.
#
# Pipeline remains a supported 2.x compatibility/dataflow resource but is no
# longer advertised as a peer of the canonical System model.
_PUBLIC_RESOURCE_KINDS = (
    "system",
    "workflow",
    "environment",
    "profile",
)

_CREATABLE_RESOURCE_KINDS = (
    *_PUBLIC_RESOURCE_KINDS,
    "pipeline",
)


_AUTHORING_ASSET_DIRECTORIES = {
    "module": "modules",
    "config": "config",
}


@dataclass(frozen=True)
class ProjectResource:
    kind: str
    name: str
    path: Path
    project_file: Path


@dataclass(frozen=True)
class ProjectAuthoringAsset:
    """Project-local authoring input that is not a canonical project resource."""

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


def _atomic_text(
    path: Path,
    text: str,
) -> None:
    """Atomically write one user- or machine-facing text document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )

    try:
        with os.fdopen(
            handle,
            "w",
            encoding="utf-8",
        ) as stream:
            stream.write(text)

        os.replace(
            temporary,
            path,
        )
    except Exception:
        Path(temporary).unlink(
            missing_ok=True
        )
        raise


def _atomic_yaml(
    path: Path,
    value: dict[str, Any],
) -> None:
    """Atomically write clean machine-oriented YAML."""

    rendered = yaml.safe_dump(
        value,
        sort_keys=False,
    )

    _atomic_text(
        path,
        rendered,
    )


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
    language: str = "en",
) -> list[Path]:
    """Create only the project manifest and local ignore rules.

    Resource and authoring directories appear only when the user explicitly
    adds the corresponding capability. Existing source repositories are
    supported: only an existing project manifest is considered a conflict.
    """

    authoring_language = (
        _normalize_authoring_language(
            language
        )
    )

    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    project_file = root / PROJECT_FILE
    if project_file.exists() and not force:
        raise FileExistsError(f"{project_file} already exists")

    project = {
        "schema": "nodrix.project/v1",
        "name": root.name.replace(" ", "-").lower(),
        "defaults": {
            "view": "compact",
            "language": authoring_language,
        },
        "build": {},
        "systems": {},
        "workflows": {},
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
    """Create a 2.x compatibility/dataflow Pipeline document.

    New executable architectures should be authored as ``nodrix.system/v1``.
    Pipeline authoring remains available so existing 2.x projects and focused
    dataflow workflows can migrate without a breaking transition.
    """

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
        "empty": f'echo "Hello from Nodrix workflow {name}"',
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
    available = ", ".join(sorted(_RESOURCE_SECTIONS))
    raise ValueError(f"Unknown resource kind {kind!r}; choose: {available}")


def _workflow_scaffold(
    name: str,
    document: dict[str, Any],
    *,
    language: str = "en",
) -> str:
    """Render a localized human-facing Workflow source file."""

    language = _normalize_authoring_language(
        language
    )

    steps = list(
        document.get("steps")
        or []
    )

    first = (
        dict(steps[0])
        if steps
        and isinstance(
            steps[0],
            dict,
        )
        else {}
    )

    step_id = str(
        first.get("id")
        or "hello"
    )

    command = str(
        first.get("run")
        or "echo Hello"
    )

    canonical = yaml.safe_dump(
        document,
        sort_keys=False,
    ).rstrip()

    if language == "ru":
        header = f"""# Nodrix Workflow
#
# Что это:
#   Workflow — конечная инженерная операция, состоящая из шагов-команд.
#   Она завершается успехом или ошибкой.
#
# Запуск:
#   plyctl workflow run {name}
#
# Python SDK:
#   from nodrix.sdk import Workflow
#   workflow = Workflow({name!r})
#   workflow.run({step_id!r}, {command!r})
#
# Ниже находится каноническое определение nodrix.workflow/v1.
#
"""

        footer = """
#
# Необязательная привязка Workflow:
#
# implements: robot.flash       # Этот Workflow реализует Operation kind.
#
# Для проектных и пакетных операций используйте namespaced kinds,
# например robot.flash или model.quantize.
#
# Необязательные поля шага:
#
#   depends_on: [prepare]       # Выполнить после указанных шагов.
#   cwd: .                      # Рабочий каталог внутри проекта.
#   timeout_seconds: 60         # Ограничение времени выполнения.
#   continue_on_error: true     # Продолжить после ошибки шага.
#
#   environment:
#     MODE: debug               # Переменные окружения шага.
#
#   when:
#     system: Linux             # Выполнять только при совпадении условия.
#
#   cache:
#     inputs: [src]
#     outputs: [build/app]      # Переиспользовать неизменившийся результат.
#
#   recipe: example.recipe      # Необязательная authoring/source подсказка.
#
# Начинайте с id + run. Добавляйте остальное только при необходимости.
"""
    else:
        header = f"""# Nodrix Workflow
#
# What:
#   A Workflow is a finite engineering operation made of command steps.
#   It finishes with success or failure.
#
# Run:
#   plyctl workflow run {name}
#
# Python SDK:
#   from nodrix.sdk import Workflow
#   workflow = Workflow({name!r})
#   workflow.run({step_id!r}, {command!r})
#
# The YAML below is the canonical nodrix.workflow/v1 definition.
#
"""

        footer = """
#
# Optional workflow binding:
#
# implements: robot.flash       # This Workflow implements this Operation kind.
#
# Use namespaced kinds such as robot.flash or model.quantize for
# project/package-specific operations.
#
# Optional step fields:
#
#   depends_on: [prepare]       # Run after earlier steps.
#   cwd: .                      # Working directory inside the project.
#   timeout_seconds: 60         # Stop a step that runs too long.
#   continue_on_error: true     # Continue after this step fails.
#
#   environment:
#     MODE: debug               # Environment values for this step.
#
#   when:
#     system: Linux             # Run only when conditions match.
#
#   cache:
#     inputs: [src]
#     outputs: [build/app]      # Reuse unchanged successful work.
#
#   recipe: example.recipe      # Optional authoring/source hint.
#
# Start with id + run. Add optional fields only when you need them.
"""

    return (
        header
        + canonical
        + "\n"
        + footer
    )


def _system_scaffold(
    name: str,
    document: dict[str, Any],
    *,
    language: str = "en",
) -> str:
    """Render a localized human-facing canonical System source file."""

    language = _normalize_authoring_language(
        language
    )

    canonical = yaml.safe_dump(
        document,
        sort_keys=False,
    ).rstrip()

    if language == "ru":
        header = f"""# Nodrix System
#
# Что это:
#   System — каноническое определение всей исполняемой системы.
#   Оно описывает targets, resources, applications, графы и связи.
#
# Проверить:
#   plyctl system validate systems/{name}.yaml
#
# Построить Plan без запуска:
#   plyctl system plan systems/{name}.yaml
#
# Запустить:
#   plyctl system run systems/{name}.yaml
#
# Просмотреть:
#   plyctl system show systems/{name}.yaml
#
# Ниже находится минимальный System Source. Пока imports/config не используются,\n# он одновременно является каноническим nodrix.system/v1 Definition.
#
"""

        footer = """
#
# Типичные следующие разделы:
#
# targets: []         # Где могут исполняться части системы.
# resources: []       # Общие зависимости и execution context.
# applications: []    # Процессы, launch-файлы и другие applications.
#
# Начинайте с identity System и добавляйте архитектуру только по необходимости.
"""
    else:
        header = f"""# Nodrix System
#
# What:
#   A System is the canonical definition of the whole executable system.
#   It describes targets, resources, applications, graphs and relations.
#
# Validate:
#   plyctl system validate systems/{name}.yaml
#
# Plan without running:
#   plyctl system plan systems/{name}.yaml
#
# Run:
#   plyctl system run systems/{name}.yaml
#
# Inspect:
#   plyctl system show systems/{name}.yaml
#
# The YAML below starts as a minimal System Source. Until imports/config\n# are used, it is also the canonical nodrix.system/v1 Definition.
#
"""

        footer = """
#
# Typical next sections:
#
# targets: []         # Where parts of the system can execute.
# resources: []       # Shared dependencies and execution context.
# applications: []    # Processes, launches or other applications.
#
# Start with the System identity and add architecture only when needed.
"""

    return (
        header
        + canonical
        + "\n"
        + footer
    )


def _environment_scaffold(
    name: str,
    document: dict[str, Any],
    *,
    language: str = "en",
) -> str:
    """Render a localized human-facing project Environment source file."""

    language = _normalize_authoring_language(
        language
    )

    canonical = yaml.safe_dump(
        document,
        sort_keys=False,
    ).rstrip()

    if language == "ru":
        header = f"""# Nodrix Environment
#
# Что это:
#   Environment описывает требования к host/process окружению.
#   Это не описание исполняемой архитектуры System.
#
# Используйте для:
#   shell setup, переменных окружения, platform constraints и checks.
#
# Связь понятий:
#   System      = что исполняется.
#   Environment = что требуется от host/process.
#   Profile     = проектный configuration overlay.
#
# Просмотреть выбранный Environment:
#   plyctl env show
#
# Проверить требования:
#   plyctl env check
#
# Экспортировать разрешённые значения:
#   plyctl env export
#
# Сделать Environment значением по умолчанию:
#   plyctl project add environment {name} --default
#
# Ниже находится configuration document nodrix.environment/v1.
#
"""

        footer = """
#
# Примеры:
#
# shell:
#   source:
#     - /opt/ros/jazzy/setup.bash
#
# environment:
#   ROS_DOMAIN_ID: "42"
#
# checks:
#   - type: command
#     command: cmake
#
# Добавляйте только те требования, которые действительно нужны операциям.
"""
    else:
        header = f"""# Nodrix Environment
#
# What:
#   An Environment describes host/process prerequisites.
#   It does not describe the executable System architecture.
#
# Use it for:
#   shell setup files, environment variables and checks.
#   Platform constraints may describe the expected host architecture.
#
# Relationship:
#   System      = what executes.
#   Environment = what the host/process requires.
#   Profile     = project configuration overlay.
#
# Inspect the currently selected Environment:
#   plyctl env show
#
# Check its prerequisites:
#   plyctl env check
#
# Export its resolved values:
#   plyctl env export
#
# Make the Environment the project default:
#   plyctl project add environment {name} --default
#
# The YAML below is the nodrix.environment/v1 configuration document.
#
"""

        footer = """
#
# Examples:
#
# shell:
#   source:
#     - /opt/ros/jazzy/setup.bash
#
# environment:
#   ROS_DOMAIN_ID: "42"
#
# checks:
#   - type: command
#     command: cmake
#
# Add only the prerequisites your operations actually require.
"""

    return (
        header
        + canonical
        + "\n"
        + footer
    )


def _profile_scaffold(
    name: str,
    document: dict[str, Any],
    *,
    language: str = "en",
) -> str:
    """Render a localized human-facing project Profile source file."""

    language = _normalize_authoring_language(
        language
    )

    canonical = yaml.safe_dump(
        document,
        sort_keys=False,
    ).rstrip()

    if language == "ru":
        header = f"""# Nodrix Profile
#
# Что это:
#   Profile — именованный configuration overlay проекта.
#   Это не исполняемый Definition и не RuntimePreset.
#
# Используйте для:
#   проектных вариантов, аппаратной настройки, variables и выбора RuntimePreset.
#
# Связь понятий:
#   Profile       = project configuration overlay.
#   RuntimePreset = execution/performance defaults.
#   Environment   = host/process prerequisites.
#
# Сделать Profile значением по умолчанию:
#   plyctl project add profile {name} --default
#
# Ниже находится configuration document nodrix.profile/v1.
#
"""

        footer = """
#
# Необязательные поля:
#
# runtime_profile: realtime-low-latency
#
# variables:
#   MAP_VOXEL_SIZE: "0.1"
#
# Начинайте с пустого Profile и добавляйте значения только для варианта проекта.
"""
    else:
        header = f"""# Nodrix Profile
#
# What:
#   A Profile is a named project configuration overlay.
#   It is not an executable Definition and it is not a RuntimePreset.
#
# Use it for:
#   Project variants, hardware tuning, variables and RuntimePreset selection.
#
# Relationship:
#   Profile       = project configuration overlay.
#   RuntimePreset = execution/performance defaults.
#   Environment   = host/process prerequisites.
#
# Make the Profile the project default:
#   plyctl project add profile {name} --default
#
# The YAML below is the nodrix.profile/v1 configuration document.
#
"""

        footer = """
#
# Optional fields:
#
# runtime_profile: realtime-low-latency
#
# variables:
#   MAP_VOXEL_SIZE: "0.1"
#
# Start with an empty Profile and add values only for a project variant.
"""

    return (
        header
        + canonical
        + "\n"
        + footer
    )


def _render_resource_scaffold(
    kind: str,
    name: str,
    document: dict[str, Any],
    *,
    language: str = "en",
) -> str:
    """Render a resource created for direct user editing.

    Canonical documents remain plain data. Human-facing resources may add
    comments that explain the model and its SDK/CLI entry points.
    """

    if kind == "workflow":
        return _workflow_scaffold(
            name,
            document,
            language=language,
        )

    if kind == "system":
        return _system_scaffold(
            name,
            document,
            language=language,
        )

    if kind == "environment":
        return _environment_scaffold(
            name,
            document,
            language=language,
        )

    if kind == "profile":
        return _profile_scaffold(
            name,
            document,
            language=language,
        )

    return yaml.safe_dump(
        document,
        sort_keys=False,
    )


def _system_module_scaffold(
    name: str,
    *,
    language: str = "en",
) -> str:
    """Render one reusable structural System authoring module."""

    language = _normalize_authoring_language(language)

    if language == "ru":
        return f"""# Nodrix System Module
#
# Что это:
#   System Module — переиспользуемая структурная часть System Source.
#   Module существует только на authoring-уровне.
#
# Это НЕ:
#   - отдельный Definition;
#   - Entity;
#   - runtime object;
#   - Python module.
#
# Подключение из System:
#
#   imports:
#     - ../modules/{name}.yaml
#
# После resolution Module исчезает, а в SystemModel остаётся только
# результирующая архитектура.
#
schema: nodrix.system-module/v1

# Добавляйте только необходимые структурные разделы:
#
# targets: []
# resources: []
# applications: []
# graphs: []
# links: []
# artifacts: []
"""

    return f"""# Nodrix System Module
#
# What:
#   A System Module is a reusable structural part of a System Source.
#   It exists only at the authoring layer.
#
# It is NOT:
#   - a separate Definition;
#   - an Entity;
#   - a runtime object;
#   - a Python module.
#
# Import it from a System:
#
#   imports:
#     - ../modules/{name}.yaml
#
# After resolution the Module disappears and only the resulting architecture
# remains in SystemModel.
#
schema: nodrix.system-module/v1

# Add only the structural sections you need:
#
# targets: []
# resources: []
# applications: []
# graphs: []
# links: []
# artifacts: []
"""


def _system_config_scaffold(
    name: str,
    *,
    language: str = "en",
) -> str:
    """Render one semantic System Config authoring document."""

    language = _normalize_authoring_language(language)

    if language == "ru":
        return f"""# Nodrix System Config
#
# Что это:
#   Config содержит semantic values, используемые при resolution System.
#   Это не Definition, не Profile и не Environment.
#
# Подключение из System:
#
#   config:
#     - ../config/{name}.yaml
#
# Одно typed-значение:
#
#   voxel_size_m: "${{config.mapping.voxel_size_m}}"
#
# Целая группа:
#
#   parameters: "${{config.mapping}}"
#
# Значения из более поздних Config-файлов перекрывают более ранние.
#
# Пример:
#
# mapping:
#   voxel_size_m: 0.1
#   point_stride: 1
#
# Добавляйте реальные значения только когда они нужны.
{{}}
"""

    return f"""# Nodrix System Config
#
# What:
#   Config contains semantic values used while resolving a System.
#   It is not a Definition, Profile, or Environment.
#
# Attach it to a System:
#
#   config:
#     - ../config/{name}.yaml
#
# One typed value:
#
#   voxel_size_m: "${{config.mapping.voxel_size_m}}"
#
# A whole group:
#
#   parameters: "${{config.mapping}}"
#
# Values from later Config files override earlier files.
#
# Example:
#
# mapping:
#   voxel_size_m: 0.1
#   point_stride: 1
#
# Add real values only when the System needs them.
{{}}
"""


def add_project_authoring_asset(
    kind: str,
    name: str,
    *,
    root: str | Path | None = None,
    force: bool = False,
) -> ProjectAuthoringAsset:
    """Create a project-local authoring asset without registering an Entity."""

    normalized_kind = (
        kind.strip()
        .lower()
        .replace("_", "-")
    )
    normalized_name = name.strip()

    if normalized_kind not in _AUTHORING_ASSET_DIRECTORIES:
        available = ", ".join(
            sorted(_AUTHORING_ASSET_DIRECTORIES)
        )
        raise ValueError(
            f"Unknown authoring asset kind {normalized_kind!r}; "
            f"choose: {available}"
        )

    if not _RESOURCE_NAME.fullmatch(normalized_name):
        raise ValueError(
            "Asset name must start with an alphanumeric character and "
            "contain only letters, digits, '.', '_' or '-'"
        )

    project_root = _project_root(root)
    project_file = project_root / PROJECT_FILE

    project = _load_yaml(project_file)
    language = _project_authoring_language(project)

    directory = _AUTHORING_ASSET_DIRECTORIES[
        normalized_kind
    ]

    target = (
        project_root
        / directory
        / f"{normalized_name}.yaml"
    )

    if target.exists() and not force:
        raise FileExistsError(
            f"{target} already exists"
        )

    if normalized_kind == "module":
        rendered = _system_module_scaffold(
            normalized_name,
            language=language,
        )
    else:
        rendered = _system_config_scaffold(
            normalized_name,
            language=language,
        )

    _atomic_text(
        target,
        rendered,
    )

    return ProjectAuthoringAsset(
        kind=normalized_kind,
        name=normalized_name,
        path=target,
        project_file=project_file,
    )


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

    if normalized_kind == "component":
        raise ValueError(
            "Standalone project Component resources are compatibility-only; "
            "define local SDK nodes, resources, and messages in components/*.py"
        )

    if normalized_kind not in _CREATABLE_RESOURCE_KINDS:
        available = ", ".join(_CREATABLE_RESOURCE_KINDS)
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
    authoring_language = (
        _project_authoring_language(
            config
        )
    )

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

    document = _resource_document(
        normalized_kind,
        normalized_name,
        template,
    )

    rendered = _render_resource_scaffold(
        normalized_kind,
        normalized_name,
        document,
        language=authoring_language,
    )

    _atomic_text(
        target,
        rendered,
    )

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
    resources = {
        resource_kind: dict(
            config.get(
                _RESOURCE_SECTIONS[resource_kind][0]
            )
            or {}
        )
        for resource_kind in _PUBLIC_RESOURCE_KINDS
    }

    legacy_pipelines = dict(
        config.get("pipelines")
        or {}
    )
    if legacy_pipelines:
        resources["pipeline"] = legacy_pipelines

    legacy_components = dict(
        config.get("components")
        or {}
    )
    if legacy_components:
        resources["component"] = legacy_components

    return resources

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
