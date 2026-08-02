#!/usr/bin/env python3
"""Validate Plyctl release metadata and repository cleanliness."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def extract(pattern: str, path: Path) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not find version in {path.relative_to(ROOT)}")
    return match.group(1)


def check_versions() -> list[str]:
    expected = read_version()
    observed = {
        "src/nodrix/__init__.py": extract(r'^__version__\s*=\s*["\']([^"\']+)["\']', ROOT / "src/nodrix/__init__.py"),
        "CITATION.cff": extract(r"^version:\s*([^\s]+)", ROOT / "CITATION.cff"),
        "src/nodrix/native/CMakeLists.txt": extract(
            r'NODRIX_RELEASE_VERSION\s+"([^"]+)"',
            ROOT / "src/nodrix/native/CMakeLists.txt",
        ),
        "packages/nodrix-compat/pyproject.toml": extract(
            r'^version\s*=\s*["\']([^"\']+)["\']',
            ROOT / "packages/nodrix-compat/pyproject.toml",
        ),
    }
    errors = [f"{path}: {value} != {expected}" for path, value in observed.items() if value != expected]

    templates = (ROOT / "src/nodrix/project_templates.py").read_text(encoding="utf-8")
    for package_name in (
        "plyctl",
        "plyctl[media,viewer]",
        "plyctl[vision,media,viewer]",
    ):
        if f"{package_name}=={expected}" not in templates:
            errors.append(f"project_templates.py does not pin {package_name}=={expected}")
    release_manifest = json.loads(
        (ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8")
    )
    if release_manifest.get("release") != expected:
        errors.append(
            "RELEASE_MANIFEST.json: "
            f"{release_manifest.get('release')} != {expected}"
        )
    compat = (ROOT / "packages/nodrix-compat/pyproject.toml").read_text(
        encoding="utf-8"
    )
    if f'"plyctl=={expected}"' not in compat:
        errors.append(f"nodrix compatibility package does not pin plyctl=={expected}")
    return errors


def check_forbidden_files() -> list[str]:
    forbidden_dirs = {"build", "dist", ".pytest_cache", ".nodrix", "__pycache__", ".venv"}
    errors: list[str] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if ".git" in relative.parts:
            continue
        if any(part in forbidden_dirs for part in relative.parts):
            errors.append(f"generated artifact present: {relative}")
            continue
        if path.is_file() and path.suffix in {".pyc", ".so", ".pyd", ".dylib"}:
            errors.append(f"compiled artifact present: {relative}")
    return sorted(set(errors))


def check_git() -> list[str]:
    if not (ROOT / ".git").exists():
        return []
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return ["git working tree is not clean"] if result.stdout.strip() else []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-version", action="store_true")
    parser.add_argument("--version-only", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()

    version = read_version()
    if args.print_version:
        print(version)
        return 0

    errors = check_versions()
    if not args.version_only:
        errors.extend(check_forbidden_files())
        if not args.allow_dirty:
            errors.extend(check_git())

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Plyctl {version} release metadata is consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
