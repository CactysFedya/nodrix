#!/usr/bin/env python3
"""Update the Plyctl release version in authoritative project files."""

from __future__ import annotations

import argparse
from datetime import date
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.-]+)?$")


def replace(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count == 0:
        raise RuntimeError(f"Pattern not found in {path.relative_to(ROOT)}")
    path.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    args = parser.parse_args()
    version = args.version.strip()
    if not VERSION_RE.fullmatch(version):
        parser.error("version must look like 1.2.3 or a valid pre-release variant")

    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    current_match = re.search(
        r'^version = "([^"]+)"',
        project_text,
        re.MULTILINE,
    )
    if current_match is None:
        raise RuntimeError("Could not determine current project version")
    previous_version = current_match.group(1)

    replace(ROOT / "pyproject.toml", r'^version = "[^"]+"', f'version = "{version}"')
    replace(ROOT / "src/nodrix/__init__.py", r'^__version__ = "[^"]+"', f'__version__ = "{version}"')
    replace(ROOT / "CITATION.cff", r"^version: [^\n]+", f"version: {version}")
    replace(
        ROOT / "CITATION.cff",
        r"^date-released: [^\n]+",
        f"date-released: {date.today().isoformat()}",
    )
    replace(
        ROOT / "packages/nodrix-compat/pyproject.toml",
        r'^version = "[^"]+"',
        f'version = "{version}"',
    )
    replace(
        ROOT / "packages/nodrix-compat/pyproject.toml",
        r'"plyctl==[^"]+"',
        f'"plyctl=={version}"',
    )
    replace(
        ROOT / "RELEASE_MANIFEST.json",
        r'"name": "[^"]+"',
        f'"name": "Plyctl {version} Release"',
    )
    replace(
        ROOT / "RELEASE_MANIFEST.json",
        r'"release": "[^"]+"',
        f'"release": "{version}"',
    )
    replace(
        ROOT / "RELEASE_MANIFEST.json",
        r'"display_release": "[^"]+"',
        f'"display_release": "{version}"',
    )
    cmake_version = re.match(r"[0-9]+\.[0-9]+\.[0-9]+", version)
    assert cmake_version is not None
    replace(
        ROOT / "src/nodrix/native/CMakeLists.txt",
        r"project\(nodrix_native VERSION [^ ]+",
        f"project(nodrix_native VERSION {cmake_version.group(0)}",
    )
    replace(
        ROOT / "src/nodrix/native/CMakeLists.txt",
        r'^set\(NODRIX_RELEASE_VERSION "[^"]+"',
        f'set(NODRIX_RELEASE_VERSION "{version}"',
    )

    templates = ROOT / "src/nodrix/project_templates.py"
    text = templates.read_text(encoding="utf-8")
    text = re.sub(r"plyctl==[0-9A-Za-z.-]+", f"plyctl=={version}", text)
    text = re.sub(r"plyctl\[viewer\]==[0-9A-Za-z.-]+", f"plyctl[viewer]=={version}", text)
    text = re.sub(r"plyctl\[media,viewer\]==[0-9A-Za-z.-]+", f"plyctl[media,viewer]=={version}", text)
    text = re.sub(
        r"plyctl\[vision,media,viewer\]==[0-9A-Za-z.-]+",
        f"plyctl[vision,media,viewer]=={version}",
        text,
    )
    templates.write_text(text, encoding="utf-8")

    docs = ROOT / "docs/conf.py"
    docs_text = docs.read_text(encoding="utf-8")
    short_version = ".".join(version.split(".")[:2])
    docs_text = re.sub(
        r'^release = "[^"]+"',
        f'release = "{version}"',
        docs_text,
        flags=re.MULTILINE,
    )
    docs_text = re.sub(
        r'^version = "[^"]+"',
        f'version = "{short_version}"',
        docs_text,
        flags=re.MULTILINE,
    )
    docs_text = re.sub(
        r'^    "github_version": "[^"]+",',
        f'    "github_version": "v{version}",',
        docs_text,
        flags=re.MULTILINE,
    )
    docs.write_text(docs_text, encoding="utf-8")

    version_tests = (
        "tests/test_plyctl_compat.py",
        "tests/test_release_101.py",
        "tests/test_release_metadata_consistency.py",
        "tests/test_v150.py",
        "tests/test_v151.py",
        "tests/test_v160.py",
        "tests/test_v170.py",
        "tests/test_v180.py",
        "tests/test_v190.py",
        "tests/test_v200.py",
    )
    for relative in version_tests:
        path = ROOT / relative
        test_text = path.read_text(encoding="utf-8")
        if previous_version in test_text:
            path.write_text(
                test_text.replace(previous_version, version),
                encoding="utf-8",
            )

    print(f"Updated Plyctl version to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
