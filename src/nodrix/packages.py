from __future__ import annotations

import hashlib
import base64
import json
import os
import platform
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
import yaml

from . import __version__

PACKAGE_FORMAT = "nodrix-package/1"
PLUGIN_ABI = 2
_SANDBOX_POLICIES = {"in_process", "process"}
MAX_PACKAGE_FILES = 4096
MAX_PACKAGE_MEMBER_BYTES = 512 * 1024 * 1024
MAX_PACKAGE_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_PACKAGE_COMPRESSION_RATIO = 200.0
MAX_PACKAGE_METADATA_BYTES = 4 * 1024 * 1024


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
    if data["format"] != PACKAGE_FORMAT:
        raise ValueError(f"Unsupported package format: {data['format']!r}")
    data.setdefault("abi", PLUGIN_ABI)
    try:
        data["abi"] = int(data["abi"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Package abi must be an integer") from exc
    platforms = data.setdefault("platforms", ["any"])
    hardware = data.setdefault("hardware", [])
    if (
        not isinstance(platforms, list)
        or not platforms
        or not all(isinstance(item, str) and item for item in platforms)
    ):
        raise ValueError("Package platforms must be a non-empty string list")
    if not isinstance(hardware, list) or not all(
        isinstance(item, str) and item for item in hardware
    ):
        raise ValueError("Package hardware must be a string list")
    sandbox = str(data.setdefault("sandbox", "in_process"))
    if sandbox not in _SANDBOX_POLICIES:
        raise ValueError(
            "Package sandbox must be in_process or process"
        )
    data["sandbox"] = sandbox
    return data


def _platform_tags() -> set[str]:
    machine = platform.machine().lower()
    architecture = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "arm64": "aarch64",
    }.get(machine, machine)
    if sys.platform.startswith("linux"):
        operating_system = "linux"
    elif sys.platform == "darwin":
        operating_system = "macos"
    elif os.name == "nt":
        operating_system = "windows"
    else:
        operating_system = sys.platform
    tags = {f"{operating_system}-{architecture}"}
    if operating_system == "macos" and architecture == "aarch64":
        tags.add("macos-arm64")
    if operating_system == "windows" and architecture == "x86_64":
        tags.add("windows-amd64")
    return tags


def _validate_runtime_compatibility(manifest: dict[str, Any]) -> None:
    requirement = str(manifest.get("nodrix", "")).strip()
    if requirement:
        try:
            compatible = SpecifierSet(requirement).contains(
                Version(__version__),
                prereleases=True,
            )
        except (InvalidSpecifier, InvalidVersion) as exc:
            raise ValueError(
                f"Invalid Nodrix compatibility requirement: {requirement!r}"
            ) from exc
        if not compatible:
            raise ValueError(
                f"Package requires Nodrix {requirement}, runtime is {__version__}"
            )
    platforms = set(manifest["platforms"])
    if "any" not in platforms and not (_platform_tags() & platforms):
        raise ValueError(
            "Package does not support this platform; "
            f"requires {sorted(platforms)}, runtime is {sorted(_platform_tags())}"
        )
    contains_native = any(
        isinstance(spec, dict) and "native" in spec
        for spec in manifest["nodes"].values()
    )
    if contains_native and manifest["abi"] != PLUGIN_ABI:
        raise ValueError(
            f"Package Plugin ABI {manifest['abi']} is incompatible with ABI {PLUGIN_ABI}"
        )


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _signature_payload(metadata: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in metadata.items() if key != "signature"}
    return json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sign_metadata(metadata: dict[str, Any], private_key_path: Path) -> dict[str, Any]:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Package signing requires `pip install nodrix[security]`"
        ) from exc
    private_key = serialization.load_pem_private_key(
        private_key_path.read_bytes(),
        password=None,
    )
    if not isinstance(private_key, ed25519.Ed25519PrivateKey):
        raise ValueError("Nodrix package signing key must be an Ed25519 private key")
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signature = private_key.sign(_signature_payload(metadata))
    return {
        "algorithm": "ed25519",
        "key_sha256": hashlib.sha256(public_der).hexdigest(),
        "value": base64.b64encode(signature).decode("ascii"),
    }


def build_package(
    directory: str | Path = ".",
    output: str | Path | None = None,
    *,
    signing_key: str | Path | None = None,
) -> Path:
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
        if signing_key is not None:
            metadata["signature"] = _sign_metadata(
                metadata,
                Path(signing_key).expanduser().resolve(),
            )
        archive.writestr("NODRIX-PACKAGE.json", json.dumps(metadata, indent=2, sort_keys=True))
    return target


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    root = target.resolve()
    for item in archive.infolist():
        destination = (target / item.filename).resolve()
        if root != destination and root not in destination.parents:
            raise ValueError(f"Unsafe package member: {item.filename}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(item, "r") as source, destination.open("xb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)


def _safe_member_name(name: str) -> PurePosixPath:
    if "\\" in name or "\x00" in name:
        raise ValueError(f"Unsafe package member separator: {name}")
    raw_parts = name.split("/")
    member = PurePosixPath(name)
    if (
        not name
        or member.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
        or any(
            ":" in part
            or part.rstrip(" .") != part
            or part.split(".", 1)[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                "COM1",
                "COM2",
                "COM3",
                "COM4",
                "COM5",
                "COM6",
                "COM7",
                "COM8",
                "COM9",
                "LPT1",
                "LPT2",
                "LPT3",
                "LPT4",
                "LPT5",
                "LPT6",
                "LPT7",
                "LPT8",
                "LPT9",
            }
            for part in raw_parts
        )
    ):
        raise ValueError(f"Unsafe package member: {name}")
    return member


def _validate_archive_limits(
    archive: zipfile.ZipFile,
    *,
    max_files: int = MAX_PACKAGE_FILES,
    max_member_bytes: int = MAX_PACKAGE_MEMBER_BYTES,
    max_uncompressed_bytes: int = MAX_PACKAGE_UNCOMPRESSED_BYTES,
    max_compression_ratio: float = MAX_PACKAGE_COMPRESSION_RATIO,
) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > max_files:
        raise ValueError(
            f"Package contains too many members: {len(members)} > {max_files}"
        )
    total = 0
    for item in members:
        _safe_member_name(item.filename)
        unix_mode = (item.external_attr >> 16) & 0xFFFF
        if unix_mode and stat.S_ISLNK(unix_mode):
            raise ValueError(
                f"Package symlink members are forbidden: {item.filename}"
            )
        if item.is_dir():
            raise ValueError(
                f"Package directory entries are forbidden: {item.filename}"
            )
        if item.file_size > max_member_bytes:
            raise ValueError(
                f"Package member is too large: {item.filename}"
            )
        total += item.file_size
        if total > max_uncompressed_bytes:
            raise ValueError("Package uncompressed-size limit exceeded")
        if (
            item.file_size > 0
            and item.file_size / max(1, item.compress_size)
            > max_compression_ratio
        ):
            raise ValueError(
                f"Package compression-ratio limit exceeded: {item.filename}"
            )
    return members


def _verify_archive(
    archive: zipfile.ZipFile,
    package_path: Path,
    *,
    public_key: str | Path | None = None,
    require_signature: bool = False,
) -> dict[str, Any]:
    members = _validate_archive_limits(archive)
    names = [item.filename for item in members]
    if len(names) != len(set(names)):
        raise ValueError("Package contains duplicate archive members")
    portable_names = [
        unicodedata.normalize("NFC", name).casefold()
        for name in names
    ]
    if len(portable_names) != len(set(portable_names)):
        raise ValueError(
            "Package contains names that collide on a supported platform"
        )
    try:
        metadata_info = archive.getinfo("NODRIX-PACKAGE.json")
    except KeyError as exc:
        raise ValueError("Package metadata is missing") from exc
    if metadata_info.file_size > MAX_PACKAGE_METADATA_BYTES:
        raise ValueError("Package metadata-size limit exceeded")
    try:
        metadata = json.loads(archive.read(metadata_info))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Package metadata is not valid JSON") from exc
    if metadata.get("format") != PACKAGE_FORMAT:
        raise ValueError("Unsupported Nodrix package format")
    raw_checksums = metadata.get("checksums")
    if not isinstance(raw_checksums, dict):
        raise ValueError("Package metadata checksums must be a mapping")
    checksums = dict(raw_checksums)
    for name, checksum in checksums.items():
        _safe_member_name(name)
        if (
            not isinstance(checksum, str)
            or len(checksum) != 64
            or any(ch not in "0123456789abcdef" for ch in checksum)
        ):
            raise ValueError(f"Invalid package checksum entry: {name}")
    expected_members = set(checksums) | {"NODRIX-PACKAGE.json"}
    if set(names) != expected_members:
        untracked = sorted(set(names) - expected_members)
        missing = sorted(expected_members - set(names))
        raise ValueError(
            f"Package member set mismatch; untracked={untracked}, missing={missing}"
        )
    for name, expected in checksums.items():
        if _hash_bytes(archive.read(name)) != expected:
            raise ValueError(f"Package checksum mismatch: {name}")
    try:
        package_manifest = yaml.safe_load(
            archive.read("nodrix.package.yaml")
        )
    except (KeyError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("Package manifest is missing or invalid") from exc
    if not isinstance(package_manifest, dict):
        raise ValueError("Package manifest must be a mapping")
    if (
        metadata.get("name") != package_manifest.get("name")
        or str(metadata.get("version", ""))
        != str(package_manifest.get("version", ""))
    ):
        raise ValueError(
            "Package metadata name/version does not match its manifest"
        )
    signature = metadata.get("signature")
    if require_signature and not signature:
        raise ValueError("Package signature is required")
    signature_verified = False
    if public_key is not None:
        if not signature or signature.get("algorithm") != "ed25519":
            raise ValueError("Package has no supported Ed25519 signature")
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ed25519
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Package signature verification requires `pip install nodrix[security]`"
            ) from exc
        key = serialization.load_pem_public_key(
            Path(public_key).expanduser().resolve().read_bytes()
        )
        if not isinstance(key, ed25519.Ed25519PublicKey):
            raise ValueError("Trusted package key must be an Ed25519 public key")
        public_der = key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        fingerprint = hashlib.sha256(public_der).hexdigest()
        if fingerprint != signature.get("key_sha256"):
            raise ValueError("Package signing-key fingerprint mismatch")
        key.verify(
            base64.b64decode(str(signature["value"]), validate=True),
            _signature_payload(metadata),
        )
        signature_verified = True
    return {
        "path": str(package_path),
        "name": metadata.get("name"),
        "version": metadata.get("version"),
        "files": len(checksums),
        "checksums": "verified",
        "signed": bool(signature),
        "signature_verified": signature_verified,
        "key_sha256": None if not signature else signature.get("key_sha256"),
    }


def verify_package(
    package: str | Path,
    *,
    public_key: str | Path | None = None,
    require_signature: bool = False,
) -> dict[str, Any]:
    package_path = Path(package).expanduser().resolve()
    with zipfile.ZipFile(package_path) as archive:
        return _verify_archive(
            archive,
            package_path,
            public_key=public_key,
            require_signature=require_signature,
        )


def install_package(
    package: str | Path,
    *,
    public_key: str | Path | None = None,
    require_signature: bool = False,
) -> dict[str, Any]:
    package_path = Path(package).expanduser().resolve()
    with zipfile.ZipFile(package_path) as archive:
        verification = _verify_archive(
            archive,
            package_path,
            public_key=public_key,
            require_signature=require_signature,
        )
        metadata = json.loads(archive.read("NODRIX-PACKAGE.json"))
        with tempfile.TemporaryDirectory(prefix="nodrix-package-") as tmp:
            temp_root = Path(tmp)
            _safe_extract(archive, temp_root)
            manifest = load_package_manifest(temp_root)
            _validate_runtime_compatibility(manifest)
            for name, expected in metadata.get("checksums", {}).items():
                path = temp_root / name
                if not path.is_file() or _hash_bytes(path.read_bytes()) != expected:
                    raise ValueError(f"Package checksum mismatch: {name}")
            target = packages_root() / manifest["name"] / manifest["version"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(
                    "Package versions are immutable and already installed: "
                    f"{manifest['name']} {manifest['version']}"
                )
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{target.name}.install-",
                    dir=target.parent,
                )
            )
            shutil.copytree(temp_root, staging, dirs_exist_ok=True)
            (staging / ".nodrix-verification.json").write_text(
                json.dumps(verification, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            try:
                os.replace(staging, target)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
    current = target.parent / "current"
    temporary_current = (
        target.parent / f".current-{os.getpid()}.tmp"
    )
    try:
        if temporary_current.exists() or temporary_current.is_symlink():
            temporary_current.unlink()
        temporary_current.symlink_to(
            target.name, target_is_directory=True
        )
        os.replace(temporary_current, current)
    except OSError:
        if temporary_current.exists() or temporary_current.is_symlink():
            temporary_current.unlink()
        marker = target.parent / "CURRENT"
        temporary_marker = target.parent / f".CURRENT-{os.getpid()}.tmp"
        temporary_marker.write_text(target.name, encoding="utf-8")
        os.replace(temporary_marker, marker)
    return {
        "name": manifest["name"],
        "version": manifest["version"],
        "path": str(target),
        "verification": verification,
    }


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


def package_verification(name: str) -> dict[str, Any]:
    root = _current_package_dir(name)
    path = root / ".nodrix-verification.json"
    if not path.is_file():
        return {
            "signed": False,
            "signature_verified": False,
            "reason": "legacy installation has no verification record",
        }
    return json.loads(path.read_text(encoding="utf-8"))


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
