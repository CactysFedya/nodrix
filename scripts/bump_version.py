#!/usr/bin/env python3
"""Update the Nodrix release version in authoritative project files."""

from __future__ import annotations

import argparse
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

    replace(ROOT / "pyproject.toml", r'^version = "[^"]+"', f'version = "{version}"')
    replace(ROOT / "src/nodrix/__init__.py", r'^__version__ = "[^"]+"', f'__version__ = "{version}"')
    replace(ROOT / "CITATION.cff", r"^version: [^\n]+", f"version: {version}")
    replace(
        ROOT / "src/nodrix/native/CMakeLists.txt",
        r"project\(nodrix_native VERSION [^ ]+",
        f"project(nodrix_native VERSION {version}",
    )

    templates = ROOT / "src/nodrix/project_templates.py"
    text = templates.read_text(encoding="utf-8")
    text = re.sub(r"nodrix==[0-9A-Za-z.-]+", f"nodrix=={version}", text)
    text = re.sub(r"nodrix\[viewer\]==[0-9A-Za-z.-]+", f"nodrix[viewer]=={version}", text)
    text = re.sub(r"nodrix\[media,viewer\]==[0-9A-Za-z.-]+", f"nodrix[media,viewer]=={version}", text)
    templates.write_text(text, encoding="utf-8")

    print(f"Updated Nodrix version to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
