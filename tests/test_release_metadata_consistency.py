from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "2.3.0b1"


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
    assert manifest["display_release"] == "2.3.0-beta.1"

    cmake = (ROOT / "src/nodrix/native/CMakeLists.txt").read_text(
        encoding="utf-8"
    )
    assert f'NODRIX_RELEASE_VERSION "{EXPECTED}"' in cmake

    docs_conf = (ROOT / "docs/conf.py").read_text(encoding="utf-8")
    assert f'release = "{EXPECTED}"' in docs_conf

    packages_dir = ROOT / "packages"
    if packages_dir.is_dir():
        compat_path = packages_dir / "nodrix-compat/pyproject.toml"
        assert compat_path.is_file()
        compat = tomllib.loads(compat_path.read_text(encoding="utf-8"))
        assert f"plyctl=={EXPECTED}" in compat["project"]["dependencies"]


def test_public_project_urls_point_to_nodrix_repository() -> None:
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    urls = pyproject["project"]["urls"]
    assert all("CactysFedya/plyctl" not in value for value in urls.values())
    assert "CactysFedya/nodrix" in urls["Repository"]
    assert urls["Documentation"].endswith("/nodrix/")
