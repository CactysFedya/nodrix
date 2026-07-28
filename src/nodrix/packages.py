from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
from typing import Any

import yaml

from . import __version__

PACKAGE_FORMAT = "nodrix-package/1"


def nodrix_home() -> Path:
    return Path(os.environ.get("NODRIX_HOME", Path.home() / ".nodrix")).expanduser().resolve()


def packages_root() -> Path:
    return nodrix_home() / "packages"


def load_package_manifest(directory: str | Path) -> dict[str, Any]:
    root = Path(directory).expanduser().resolve()
    path = root / "nodrix.package.yaml"
    if not path.is_file():
        raise ValueError(f"Package manifest not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    name = str(data.get("name", "")).strip()
    version = str(data.get("version", "")).strip()
    nodes = data.get("nodes") or {}
    if not name or not version or not isinstance(nodes, dict):
        raise ValueError("nodrix.package.yaml requires name, version, and nodes mapping")
    data["name"] = name
    data["version"] = version
    data["nodes"] = nodes
    data.setdefault("format", PACKAGE_FORMAT)
    return data


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_package(directory: str | Path = ".", output: str | Path | None = None) -> Path:
    root = Path(directory).expanduser().resolve()
    manifest = load_package_manifest(root)
    target = (
        Path(output).expanduser().resolve()
        if output
        else root / "dist" / f"{manifest['name']}-{manifest['version']}.ndpkg"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.resolve() != target
        and not any(part in {".nodrix", "__pycache__", ".git", "dist", "build"} for part in path.relative_to(root).parts)
    )
    checksums: dict[str, str] = {}
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            rel = path.relative_to(root).as_posix()
            data = path.read_bytes()
            checksums[rel] = _hash_bytes(data)
            archive.writestr(rel, data)
        metadata = {
            "format": PACKAGE_FORMAT,
            "name": manifest["name"],
            "version": manifest["version"],
            "built_with": __version__,
            "checksums": checksums,
        }
        archive.writestr("NODRIX-PACKAGE.json", json.dumps(metadata, indent=2, sort_keys=True))
    return target


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    root = target.resolve()
    for item in archive.infolist():
        destination = (target / item.filename).resolve()
        if root != destination and root not in destination.parents:
            raise ValueError(f"Unsafe package member: {item.filename}")
    archive.extractall(target)


def install_package(package: str | Path) -> dict[str, Any]:
    package_path = Path(package).expanduser().resolve()
    with zipfile.ZipFile(package_path) as archive:
        metadata = json.loads(archive.read("NODRIX-PACKAGE.json"))
        if metadata.get("format") != PACKAGE_FORMAT:
            raise ValueError("Unsupported Nodrix package format")
        with tempfile.TemporaryDirectory(prefix="nodrix-package-") as tmp:
            temp_root = Path(tmp)
            _safe_extract(archive, temp_root)
            manifest = load_package_manifest(temp_root)
            requirement = str(manifest.get("nodrix", "")).strip()
            if requirement and ">=1.0" in requirement and "<2.0" in requirement and not __version__.startswith("1."):
                raise ValueError(f"Package requires Nodrix {requirement}, runtime is {__version__}")
            for name, expected in metadata.get("checksums", {}).items():
                path = temp_root / name
                if not path.is_file() or _hash_bytes(path.read_bytes()) != expected:
                    raise ValueError(f"Package checksum mismatch: {name}")
            target = packages_root() / manifest["name"] / manifest["version"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(temp_root, target)
    current = target.parent / "current"
    try:
        if current.is_symlink() or current.exists():
            current.unlink()
        current.symlink_to(target.name, target_is_directory=True)
    except OSError:
        (target.parent / "CURRENT").write_text(target.name, encoding="utf-8")
    return {"name": manifest["name"], "version": manifest["version"], "path": str(target)}


def _current_package_dir(name: str) -> Path:
    base = packages_root() / name
    current = base / "current"
    if current.exists():
        return current.resolve()
    marker = base / "CURRENT"
    if marker.is_file():
        return base / marker.read_text(encoding="utf-8").strip()
    versions = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True) if base.is_dir() else []
    if not versions:
        raise LookupError(f"Nodrix package is not installed: {name}")
    return versions[0]


def list_packages() -> list[dict[str, Any]]:
    root = packages_root()
    result: list[dict[str, Any]] = []
    if not root.is_dir():
        return result
    for package_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            current = _current_package_dir(package_dir.name)
            manifest = load_package_manifest(current)
            result.append({"name": manifest["name"], "version": manifest["version"], "path": str(current), "nodes": sorted(manifest["nodes"])})
        except Exception:
            continue
    return result


def package_info(name: str) -> dict[str, Any]:
    root = _current_package_dir(name)
    manifest = load_package_manifest(root)
    return {**manifest, "path": str(root)}


def remove_package(name: str) -> bool:
    root = packages_root() / name
    if not root.exists():
        return False
    shutil.rmtree(root)
    return True


def resolve_package_node(reference: str) -> str:
    """Resolve ``package/node`` to an absolute Python or native plugin reference."""
    if reference.startswith(("./", "../", "/", "native:")) or reference.count("/") != 1:
        return reference
    package_name, node_name = reference.split("/", 1)
    try:
        root = _current_package_dir(package_name)
    except LookupError:
        return reference
    manifest = load_package_manifest(root)
    spec = manifest["nodes"].get(node_name)
    if spec is None:
        raise LookupError(f"Package {package_name!r} has no node {node_name!r}")
    if isinstance(spec, str):
        spec = {"python": spec}
    if "python" in spec:
        module, class_name = str(spec["python"]).rsplit(":", 1)
        return f"{(root / module).resolve()}:{class_name}"
    if "native" in spec:
        library, node_type = str(spec["native"]).rsplit("#", 1)
        return f"native:{(root / library).resolve()}#{node_type}"
    raise ValueError(f"Invalid node specification for {reference}: {spec!r}")
