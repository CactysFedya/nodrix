from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (
        ROOT
        / path
    ).read_text(
        encoding="utf-8"
    )


def test_readme_is_system_first() -> None:
    text = _read("README.md")

    assert (
        "executable system architecture platform"
        in text
    )

    assert (
        "Pipeline model remains supported"
        in text
    )


def test_documentation_home_is_system_first() -> None:
    text = _read(
        "docs/index.md"
    )

    assert (
        "executable system architecture platform"
        in text
    )

    assert (
        "canonical `System` model"
        in text
    )


def test_pipeline_os_page_is_explicitly_compatibility_scoped() -> None:
    text = _read(
        "docs/concepts/pipeline-os.md"
    )

    assert (
        "2.x compatibility model"
        in text
    )

    assert (
        "canonical architecture model is now `System`"
        in text
    )


def test_self_describing_standard_exists_in_both_languages() -> None:
    english = _read(
        "docs/concepts/self-describing-yaml.md"
    )

    russian = _read(
        "docs/ru/concepts/self-describing-yaml.md"
    )

    assert (
        "Self-Describing, but never misleading"
        in english
    )

    assert (
        "Self-Describing, but never misleading"
        in russian
    )

    assert "language: en" in english
    assert "language: ru" in russian


def test_self_describing_standard_preserves_canonical_vocabulary() -> None:
    english = _read(
        "docs/concepts/self-describing-yaml.md"
    )

    russian = _read(
        "docs/ru/concepts/self-describing-yaml.md"
    )

    for text in (
        english,
        russian,
    ):
        assert "targets: []" in text
        assert "resources: []" in text
        assert "applications: []" in text
        assert "RuntimePreset" in text
