"""Declarative Build Recipe API compiled into normal Nodrix workflows.

The recipe layer is deliberately a control-plane convenience.  It does not
replace CMake, colcon, pip, or the workflow executor.  Instead it converts a
small, typed-ish project ``build:`` section into ``nodrix.workflow/v1`` steps,
which means the existing logging, environment handling, conditions, cache, and
``--rebuild`` behavior stay authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Callable

import yaml

from .storage_layout import StorageLayout

from .workspace import PROJECT_FILE, find_workspace


@dataclass(frozen=True, slots=True)
class BuildRecipeInfo:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class BuildRecipeContext:
    root: Path
    name: str
    config: dict[str, Any]


RecipeCompiler = Callable[[BuildRecipeContext], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _RecipeDefinition:
    info: BuildRecipeInfo
    compiler: RecipeCompiler


_RECIPES: dict[str, _RecipeDefinition] = {}


def _register(name: str, description: str) -> Callable[[RecipeCompiler], RecipeCompiler]:
    def decorator(compiler: RecipeCompiler) -> RecipeCompiler:
        if name in _RECIPES:
            raise RuntimeError(f"duplicate built-in build recipe: {name}")
        _RECIPES[name] = _RecipeDefinition(
            info=BuildRecipeInfo(name=name, description=description),
            compiler=compiler,
        )
        return compiler

    return decorator


def available_build_recipes() -> tuple[BuildRecipeInfo, ...]:
    """Return built-in high-level build recipes exposed by Nodrix 2.7."""

    return tuple(item.info for _, item in sorted(_RECIPES.items()))


def _project_root(value: str | Path | None = None) -> Path:
    selected = Path(value or Path.cwd()).expanduser().resolve()
    root = find_workspace(selected)
    if root is None:
        if (selected / PROJECT_FILE).is_file():
            return selected
        raise LookupError(f"No {PROJECT_FILE} found from {selected}")
    return root


def _load_project(root: Path) -> dict[str, Any]:
    path = root / PROJECT_FILE
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return dict(value)


def _list(value: Any, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a string or array")
    return [str(item) for item in value]


def _mapping(value: Any, field: str) -> dict[str, str]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    return {str(key): str(item) for key, item in value.items()}


def _inside_project(root: Path, value: str | Path, field: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes the project root: {resolved}") from exc
    return resolved


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix() or "."


def _shell_join(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _source_prefix(root: Path, config: dict[str, Any]) -> list[str]:
    sources = _list(config.get("setup"), "setup")
    if not sources:
        return []
    if os.name == "nt":
        raise ValueError("recipe.setup currently requires a POSIX shell")
    commands: list[str] = []
    for raw in sources:
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
        if not path.is_absolute():
            path = root / path
        commands.append(f"source {shlex.quote(str(path.resolve()))}")
    return commands


def _common_step(
    context: BuildRecipeContext,
    *,
    command_lines: list[str],
    cwd: Path,
    cache_inputs: list[str],
    cache_outputs: list[str],
    cache_environment: list[str],
) -> dict[str, Any]:
    config = context.config
    dependency_commands = [
        str(item) for item in config.get("_dependency_setup_commands", [])
    ]
    step: dict[str, Any] = {
        "id": context.name,
        "cwd": _relative(context.root, cwd),
        "run": "\n".join(
            [*dependency_commands, *_source_prefix(context.root, config), *command_lines]
        ),
    }

    environment = _mapping(config.get("environment"), "environment")
    if environment:
        step["environment"] = environment
    if "when" in config:
        step["when"] = config["when"]
    if config.get("timeout_seconds") is not None:
        step["timeout_seconds"] = float(config["timeout_seconds"])
    if bool(config.get("continue_on_error", False)):
        step["continue_on_error"] = True

    raw_cache = config.get("cache", "auto")
    if raw_cache not in (False, None, "off", "false"):
        cache: dict[str, Any] = {
            "inputs": cache_inputs,
            "outputs": cache_outputs,
            "environment": cache_environment,
        }
        if isinstance(raw_cache, dict):
            for key in ("inputs", "outputs", "environment"):
                if key in raw_cache:
                    cache[key] = _list(raw_cache[key], f"cache.{key}")
        elif raw_cache not in (True, "auto", "on", "true"):
            raise ValueError(
                "cache must be auto/true/false or a mapping with "
                "inputs/outputs/environment"
            )
        step["cache"] = cache
    return step


def _cmake_recipe(context: BuildRecipeContext, build_type: str) -> dict[str, Any]:
    config = context.config
    source = _inside_project(
        context.root,
        str(config.get("source") or "."),
        f"build.{context.name}.source",
    )
    build_dir = _inside_project(
        context.root,
        str(config.get("build_dir") or f".nodrix/build/{context.name}"),
        f"build.{context.name}.build_dir",
    )

    configure = [
        "cmake",
        "-S",
        str(source),
        "-B",
        str(build_dir),
        f"-DCMAKE_BUILD_TYPE={build_type}",
    ]
    generator = config.get("generator")
    if generator:
        configure.extend(["-G", str(generator)])
    configure.extend(_list(config.get("configure_args"), "configure_args"))

    build = ["cmake", "--build", str(build_dir)]
    parallel = config.get("parallel", "auto")
    if parallel not in (False, None, 0, "off", "false"):
        build.append("--parallel")
        if parallel not in (True, "auto", "on", "true"):
            build.append(str(int(parallel)))
    targets = _list(config.get("targets"), "targets")
    if targets:
        build.extend(["--target", *targets])
    build.extend(_list(config.get("build_args"), "build_args"))

    lines = [_shell_join(configure), _shell_join(build)]
    outputs = [_relative(context.root, build_dir)]

    install = bool(config.get("install", False) or config.get("install_prefix"))
    if install:
        prefix = _inside_project(
            context.root,
            str(config.get("install_prefix") or f".nodrix/prefix/{context.name}"),
            f"build.{context.name}.install_prefix",
        )
        install_command = ["cmake", "--install", str(build_dir), "--prefix", str(prefix)]
        install_command.extend(_list(config.get("install_args"), "install_args"))
        lines.append(_shell_join(install_command))
        outputs.append(_relative(context.root, prefix))

    step = _common_step(
        context,
        command_lines=lines,
        cwd=context.root,
        cache_inputs=[_relative(context.root, source)],
        cache_outputs=outputs,
        cache_environment=[
            "CC",
            "CXX",
            "CMAKE_GENERATOR",
            "CMAKE_BUILD_PARALLEL_LEVEL",
            "CMAKE_PREFIX_PATH",
        ],
    )
    if install:
        if os.name == "nt":
            step["_build_provides"] = [
                f"set CMAKE_PREFIX_PATH={prefix};%CMAKE_PREFIX_PATH%"
            ]
        else:
            step["_build_provides"] = [
                f"export CMAKE_PREFIX_PATH={shlex.quote(str(prefix))}:\"${{CMAKE_PREFIX_PATH:-}}\""
            ]
    return step


@_register("cmake.release", "Configure and build a CMake project in Release mode")
def _cmake_release(context: BuildRecipeContext) -> dict[str, Any]:
    return _cmake_recipe(context, "Release")


@_register("cmake.debug", "Configure and build a CMake project in Debug mode")
def _cmake_debug(context: BuildRecipeContext) -> dict[str, Any]:
    return _cmake_recipe(context, "Debug")


@_register("ros2.colcon", "Build a ROS 2 workspace with colcon")
def _ros2_colcon(context: BuildRecipeContext) -> dict[str, Any]:
    config = context.config
    workspace = _inside_project(
        context.root,
        str(config.get("workspace") or "."),
        f"build.{context.name}.workspace",
    )
    source_dir = _inside_project(
        workspace,
        str(config.get("source_dir") or "src"),
        f"build.{context.name}.source_dir",
    )
    # source_dir is constrained to workspace above, but cache paths are project-relative.
    try:
        source_dir.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(
            f"build.{context.name}.source_dir escapes the workspace: {source_dir}"
        ) from exc

    command = ["colcon", "build"]
    if bool(config.get("symlink_install", True)):
        command.append("--symlink-install")
    packages = _list(config.get("packages"), "packages")
    if packages:
        command.extend(["--packages-select", *packages])
    cmake_args = _list(config.get("cmake_args"), "cmake_args")
    if cmake_args:
        command.extend(["--cmake-args", *cmake_args])
    command.extend(_list(config.get("args"), "args"))

    step = _common_step(
        context,
        command_lines=[_shell_join(command)],
        cwd=workspace,
        cache_inputs=[_relative(context.root, source_dir)],
        cache_outputs=[_relative(context.root, workspace / "install")],
        cache_environment=[
            "ROS_DISTRO",
            "AMENT_PREFIX_PATH",
            "CMAKE_PREFIX_PATH",
            "COLCON_DEFAULTS_FILE",
            "CC",
            "CXX",
        ],
    )
    setup = workspace / "install" / ("setup.bat" if os.name == "nt" else "setup.bash")
    if os.name == "nt":
        step["_build_provides"] = [f"call {setup}"]
    else:
        step["_build_provides"] = [f"source {shlex.quote(str(setup))}"]
    return step


@_register("python.editable", "Install a Python project in editable mode")
def _python_editable(context: BuildRecipeContext) -> dict[str, Any]:
    config = context.config
    source = _inside_project(
        context.root,
        str(config.get("source") or "."),
        f"build.{context.name}.source",
    )
    command = [sys.executable, "-m", "pip", "install", "-e", str(source)]
    if bool(config.get("no_build_isolation", True)):
        command.append("--no-build-isolation")
    command.extend(_list(config.get("args"), "args"))

    # Editable installs do not have a portable project-local output marker, so
    # default to no cache.  Users may opt in with an explicit cache mapping.
    if "cache" not in config:
        config = {**config, "cache": False}
        context = BuildRecipeContext(context.root, context.name, config)
    return _common_step(
        context,
        command_lines=[_shell_join(command)],
        cwd=context.root,
        cache_inputs=[_relative(context.root, source)],
        cache_outputs=[],
        cache_environment=["VIRTUAL_ENV", "PATH"],
    )


def _dependencies(name: str, config: dict[str, Any]) -> list[str]:
    return _list(config.get("depends_on"), f"build.{name}.depends_on")


def _topological_order(recipes: dict[str, dict[str, Any]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []

    def visit(name: str, stack: list[str]) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle = " -> ".join([*stack, name])
            raise ValueError(f"build recipe dependency cycle: {cycle}")
        visiting.add(name)
        config = recipes[name]
        for dependency in _dependencies(name, config):
            if dependency not in recipes:
                raise ValueError(
                    f"build recipe {name!r} depends on unknown recipe {dependency!r}"
                )
            visit(dependency, [*stack, name])
        visiting.remove(name)
        visited.add(name)
        order.append(name)

    for name in recipes:
        visit(name, [])
    return order


def _recipe_mapping(project: dict[str, Any], project_file: Path) -> dict[str, dict[str, Any]]:
    raw = project.get("build")
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{project_file} build must be a mapping")

    recipes: dict[str, dict[str, Any]] = {}
    for raw_name, raw_config in raw.items():
        name = str(raw_name).strip()
        if not name:
            raise ValueError("build recipe name cannot be empty")
        if not isinstance(raw_config, dict):
            raise ValueError(f"build.{name} must be a mapping")
        config = dict(raw_config)
        uses = str(config.get("uses") or "").strip()
        if not uses:
            raise ValueError(f"build.{name}.uses is required")
        recipes[name] = config
    return recipes


def project_has_build_recipes(root: str | Path | None = None) -> bool:
    project_root = _project_root(root)
    project = _load_project(project_root)
    return bool(_recipe_mapping(project, project_root / PROJECT_FILE))


def compile_project_build_workflow(
    root: str | Path | None = None,
    *,
    project: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Path] | None:
    """Compile ``nodrix.yaml#build`` into an inspectable workflow document.

    Returns ``None`` when the project does not declare Build Recipes.  This is
    what allows ``workflows/build.yaml`` to remain a fully compatible fallback.
    """

    project_root = _project_root(root)
    project_file = project_root / PROJECT_FILE
    document = dict(project) if project is not None else _load_project(project_root)
    recipes = _recipe_mapping(document, project_file)
    if not recipes:
        return None

    steps: list[dict[str, Any]] = []
    provided_commands: dict[str, list[str]] = {}
    for name in _topological_order(recipes):
        config = recipes[name]
        dependencies = _dependencies(name, config)
        inherited_commands: list[str] = []
        for dependency in dependencies:
            for command in provided_commands.get(dependency, []):
                if command not in inherited_commands:
                    inherited_commands.append(command)
        effective_config = dict(config)
        if inherited_commands:
            effective_config["_dependency_setup_commands"] = inherited_commands
        uses = str(config["uses"])
        definition = _RECIPES.get(uses)
        if definition is None:
            available = ", ".join(sorted(_RECIPES))
            raise ValueError(
                f"build.{name}.uses references unknown recipe {uses!r}; "
                f"available: {available}"
            )
        step = definition.compiler(
            BuildRecipeContext(root=project_root, name=name, config=effective_config)
        )
        own_commands = [str(item) for item in step.pop("_build_provides", [])]
        combined_commands = list(inherited_commands)
        for command in own_commands:
            if command not in combined_commands:
                combined_commands.append(command)
        provided_commands[name] = combined_commands
        step["recipe"] = uses
        if dependencies:
            step["depends_on"] = dependencies
        steps.append(step)

    workflow: dict[str, Any] = {
        "schema": "nodrix.workflow/v1",
        "name": "build",
        "generated": {
            "schema": "nodrix.build-recipes/v1",
            "source": "nodrix.yaml#build",
        },
        "steps": steps,
    }
    output = (
        StorageLayout(
            project_root
        ).generated_root
        / "build.workflow.yaml"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(workflow, sort_keys=False)
    if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
        output.write_text(rendered, encoding="utf-8")
    return workflow, output


__all__ = [
    "BuildRecipeInfo",
    "available_build_recipes",
    "compile_project_build_workflow",
    "project_has_build_recipes",
]
