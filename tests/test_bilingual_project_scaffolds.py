from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
)


def _create(
    root: Path,
    language: str,
    kind: str,
):
    create_progressive_project(
        root,
        language=language,
    )

    return add_project_resource(
        kind,
        f"example-{kind}",
        root=root,
    )


@pytest.mark.parametrize(
    "kind",
    (
        "system",
        "workflow",
        "environment",
        "profile",
    ),
)
def test_english_project_scaffolds_use_english_comments(
    tmp_path: Path,
    kind: str,
) -> None:
    resource = _create(
        tmp_path,
        "en",
        kind,
    )

    text = resource.path.read_text(
        encoding="utf-8"
    )

    assert "# What:" in text

    project = yaml.safe_load(
        (
            tmp_path
            / "nodrix.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        project["defaults"]["language"]
        == "en"
    )


@pytest.mark.parametrize(
    "kind",
    (
        "system",
        "workflow",
        "environment",
        "profile",
    ),
)
def test_russian_project_scaffolds_use_russian_comments(
    tmp_path: Path,
    kind: str,
) -> None:
    resource = _create(
        tmp_path,
        "ru",
        kind,
    )

    text = resource.path.read_text(
        encoding="utf-8"
    )

    assert "# Что это:" in text

    project = yaml.safe_load(
        (
            tmp_path
            / "nodrix.yaml"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert (
        project["defaults"]["language"]
        == "ru"
    )


def test_profile_gets_self_describing_scaffold(
    tmp_path: Path,
) -> None:
    resource = _create(
        tmp_path,
        "en",
        "profile",
    )

    text = resource.path.read_text(
        encoding="utf-8"
    )

    assert "# Nodrix Profile" in text
    assert "RuntimePreset" in text
    assert "configuration overlay" in text


def test_old_project_without_language_defaults_to_english(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    project_file = (
        tmp_path
        / "nodrix.yaml"
    )

    project = yaml.safe_load(
        project_file.read_text(
            encoding="utf-8"
        )
    )

    project["defaults"].pop(
        "language"
    )

    project_file.write_text(
        yaml.safe_dump(
            project,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    resource = add_project_resource(
        "system",
        "robot",
        root=tmp_path,
    )

    assert "# What:" in (
        resource.path.read_text(
            encoding="utf-8"
        )
    )


def test_unknown_project_language_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="Unknown project language",
    ):
        create_progressive_project(
            tmp_path,
            language="de",
        )
