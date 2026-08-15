from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "2.8.0"


def test_release_metadata_uses_one_public_version() -> None:
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["project"]["version"] == EXPECTED

    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert re.search(rf"(?m)^version:\s*{re.escape(EXPECTED)}\s*$", citation)

    manifest = json.loads(
        (ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["release"] == EXPECTED
    assert manifest["display_release"] == EXPECTED

    cmake = (ROOT / "src/nodrix/native/CMakeLists.txt").read_text(
        encoding="utf-8"
    )
    assert f'NODRIX_RELEASE_VERSION "{EXPECTED}"' in cmake

    docs_conf = (ROOT / "docs/conf.py").read_text(encoding="utf-8")
    assert f'release = "{EXPECTED}"' in docs_conf

    compat = tomllib.loads(
        (ROOT / "packages/nodrix-compat/pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    assert f"plyctl=={EXPECTED}" in compat["project"]["dependencies"]


def test_public_project_urls_point_to_nodrix_repository() -> None:
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    urls = pyproject["project"]["urls"]
    assert all("CactysFedya/plyctl" not in value for value in urls.values())
    assert "CactysFedya/nodrix" in urls["Repository"]
    assert urls["Documentation"].endswith("/nodrix/")
