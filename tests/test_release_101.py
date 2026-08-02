from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_patch_release_metadata() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    assert config["project"]["version"] == "2.2.0a5"
    assert "setuptools>=68" in config["build-system"]["requires"]
    assert "license" not in config["project"]
    assert (
        "License :: OSI Approved :: Apache Software License"
        in config["project"]["classifiers"]
    )


def test_release_matrix_excludes_intel_mac_and_uses_node24_actions() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    assert config["tool"]["cibuildwheel"]["windows"]["archs"] == ["AMD64"]

    workflow_path = ROOT / ".github/workflows/publish.yml"
    if not workflow_path.exists():
        return
    workflow = workflow_path.read_text(encoding="utf-8")
    assert "macos-15-intel" not in workflow
    assert "macos-latest" in workflow
    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "actions/upload-artifact@v6" in workflow
    assert "actions/download-artifact@v6" in workflow
    assert 'cibuildwheel==3.4.1' in workflow


def test_offline_install_assets_exist() -> None:
    assert (ROOT / "scripts/install_offline.sh").is_file()
    assert (ROOT / "offline-requirements.txt").is_file()
    assert (ROOT / "docs/OFFLINE_INSTALL_RU.md").is_file()
