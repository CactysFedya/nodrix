from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any, Iterable

from . import __version__
from .manifest import load_manifest_details
from .packages import resolve_package_node

LOCK_FORMAT = "nodrix-lock/1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_files(project_dir: Path, manifest_path: Path) -> Iterable[Path]:
    details = load_manifest_details(manifest_path)
    manifest = details.manifest
    yield manifest_path
    yield from details.block_files.values()
    package_roots: set[Path] = set()
    for config in manifest.nodes.values():
        uses = resolve_package_node(config.uses)
        if uses.startswith("native:"):
            library = uses.removeprefix("native:").split("#", 1)[0]
            path = Path(library)
            if not path.is_absolute():
                path = project_dir / path
            if path.is_file():
                resolved = path.resolve()
                yield resolved
                for parent in (resolved.parent, *resolved.parents):
                    if (parent / "nodrix.package.yaml").is_file():
                        package_roots.add(parent)
                        break
        elif ":" in uses:
            module_ref = uses.rsplit(":", 1)[0]
            if module_ref.endswith(".py") or "/" in module_ref or "\\" in module_ref:
                path = Path(module_ref)
                if not path.is_absolute():
                    path = project_dir / path
                if path.is_file():
                    yield path.resolve()
    for dirname in ("models", "configs", "types"):
        root = project_dir / dirname
        if root.is_dir():
            yield from sorted(p for p in root.rglob("*") if p.is_file())
    package_manifest = project_dir / "nodrix.package.yaml"
    if package_manifest.is_file():
        yield package_manifest


def _dependency_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("pydantic", "PyYAML", "rich", "typer", "numpy", "opencv-python"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return result


def build_lock(manifest_path: str | Path = "pipeline.yaml") -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser().resolve()
    project_dir = manifest_path.parent
    files: dict[str, dict[str, Any]] = {}
    seen: set[Path] = set()
    for path in _candidate_files(project_dir, manifest_path):
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        try:
            rel = str(path.relative_to(project_dir))
        except ValueError:
            rel = str(path)
        files[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    return {
        "format": LOCK_FORMAT,
        "runtime": {"name": "nodrix", "version": __version__, "plugin_abi": 2},
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "executable": sys.executable,
        },
        "dependencies": _dependency_versions(),
        "files": dict(sorted(files.items())),
    }


def write_lock(manifest_path: str | Path = "pipeline.yaml", output: str | Path | None = None) -> Path:
    manifest_path = Path(manifest_path).expanduser().resolve()
    target = Path(output).expanduser().resolve() if output else manifest_path.parent / "nodrix.lock"
    target.write_text(json.dumps(build_lock(manifest_path), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def verify_lock(
    manifest_path: str | Path = "pipeline.yaml",
    lock_path: str | Path | None = None,
    *,
    mode: str = "compatible",
) -> dict[str, Any]:
    if mode not in {"compatible", "exact"}:
        raise ValueError("lock verification mode must be compatible or exact")
    manifest_path = Path(manifest_path).expanduser().resolve()
    path = Path(lock_path).expanduser().resolve() if lock_path else manifest_path.parent / "nodrix.lock"
    expected = json.loads(path.read_text(encoding="utf-8"))
    actual = build_lock(manifest_path)
    issues: list[str] = []
    if expected.get("format") != LOCK_FORMAT:
        issues.append(f"unsupported lock format: {expected.get('format')!r}")
    expected_runtime = expected.get("runtime", {})
    if expected_runtime.get("version") != __version__:
        issues.append(f"runtime version changed: expected {expected_runtime.get('version')}, actual {__version__}")
    if expected_runtime.get("plugin_abi") != actual.get("runtime", {}).get("plugin_abi"):
        issues.append(
            "plugin ABI changed: "
            f"expected {expected_runtime.get('plugin_abi')}, actual {actual.get('runtime', {}).get('plugin_abi')}"
        )
    expected_dependencies = dict(expected.get("dependencies") or {})
    actual_dependencies = dict(actual.get("dependencies") or {})
    for name, version in expected_dependencies.items():
        if name not in actual_dependencies:
            issues.append(f"missing locked dependency: {name}=={version}")
        elif actual_dependencies[name] != version:
            issues.append(
                f"dependency changed: {name} expected {version}, actual {actual_dependencies[name]}"
            )
    for name, version in actual_dependencies.items():
        if name not in expected_dependencies:
            issues.append(f"new unlocked dependency: {name}=={version}")
    expected_environment = dict(expected.get("environment") or {})
    actual_environment = dict(actual.get("environment") or {})
    for name in ("implementation", "machine"):
        if expected_environment.get(name) != actual_environment.get(name):
            issues.append(
                f"environment changed: {name} expected {expected_environment.get(name)}, "
                f"actual {actual_environment.get(name)}"
            )
    expected_python = str(expected_environment.get("python", ""))
    actual_python = str(actual_environment.get("python", ""))
    if expected_python.split(".")[:2] != actual_python.split(".")[:2]:
        issues.append(f"Python ABI changed: expected {expected_python}, actual {actual_python}")
    if mode == "exact":
        for name in ("python", "platform", "executable"):
            if expected_environment.get(name) != actual_environment.get(name):
                issues.append(
                    f"exact environment changed: {name} expected {expected_environment.get(name)}, "
                    f"actual {actual_environment.get(name)}"
                )
    expected_files = expected.get("files", {})
    actual_files = actual.get("files", {})
    for name, spec in expected_files.items():
        if name not in actual_files:
            issues.append(f"missing locked file: {name}")
        elif actual_files[name].get("sha256") != spec.get("sha256"):
            issues.append(f"checksum changed: {name}")
    for name in actual_files:
        if name not in expected_files:
            issues.append(f"new unlocked file: {name}")
    return {"ok": not issues, "path": str(path), "issues": issues, "expected": expected, "actual": actual}
