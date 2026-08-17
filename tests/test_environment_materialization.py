from __future__ import annotations

from pathlib import Path

import pytest

from nodrix.environment_materialization import (
    materialize_environment,
    source_environment,
)


def _script(
    path: Path,
    content: str,
) -> Path:
    path.write_text(
        content,
        encoding="utf-8",
    )
    return path


def test_source_environment_captures_shell_exports(
    tmp_path: Path,
) -> None:
    first = _script(
        tmp_path / "first.bash",
        (
            'export FROM_FIRST="yes"\n'
            'export SHARED="from-source"\n'
        ),
    )

    second = _script(
        tmp_path / "second.bash",
        (
            'export CHAIN="${FROM_FIRST}-second"\n'
        ),
    )

    base = {
        "SHARED": "from-base",
        "BASE_ONLY": "present",
    }

    resolved = source_environment(
        base=base,
        sources=(
            first,
            second,
        ),
        cwd=tmp_path,
        activation_label="test environment",
    )

    assert (
        resolved["FROM_FIRST"]
        == "yes"
    )

    assert (
        resolved["CHAIN"]
        == "yes-second"
    )

    # Plain shell sourcing preserves legacy Workflow semantics:
    # sourced values may override values present in the base mapping.
    assert (
        resolved["SHARED"]
        == "from-source"
    )

    assert (
        resolved["BASE_ONLY"]
        == "present"
    )

    assert base == {
        "SHARED": "from-base",
        "BASE_ONLY": "present",
    }


def test_materialized_explicit_variables_win_after_sources(
    tmp_path: Path,
) -> None:
    setup = _script(
        tmp_path / "setup.bash",
        (
            'export SHARED="from-source"\n'
            'export SOURCE_ONLY="source"\n'
        ),
    )

    resolved = materialize_environment(
        base={
            "BASE_ONLY": "base",
        },
        variables={
            "SHARED": "explicit",
            "PROFILE_ONLY": "profile",
        },
        sources=(
            setup,
        ),
        cwd=tmp_path,
        activation_label="test environment",
    )

    assert (
        resolved["SHARED"]
        == "explicit"
    )

    assert (
        resolved["SOURCE_ONLY"]
        == "source"
    )

    assert (
        resolved["PROFILE_ONLY"]
        == "profile"
    )

    assert (
        resolved["BASE_ONLY"]
        == "base"
    )


def test_materialization_does_not_mutate_base(
    tmp_path: Path,
) -> None:
    base = {
        "ORIGINAL": "yes",
    }

    resolved = materialize_environment(
        base=base,
        variables={
            "NEW_VALUE": "new",
        },
        sources=(),
        cwd=tmp_path,
    )

    assert base == {
        "ORIGINAL": "yes",
    }

    assert resolved == {
        "ORIGINAL": "yes",
        "NEW_VALUE": "new",
    }


def test_missing_source_preserves_existing_error_contract(
    tmp_path: Path,
) -> None:
    missing = (
        tmp_path
        / "missing-setup.bash"
    )

    with pytest.raises(
        FileNotFoundError,
        match="Environment source files not found",
    ):
        source_environment(
            base={},
            sources=(
                missing,
            ),
            cwd=tmp_path,
        )


def test_source_failure_uses_requested_activation_label(
    tmp_path: Path,
) -> None:
    broken = _script(
        tmp_path / "broken.bash",
        (
            'echo "broken setup" >&2\n'
            "exit 7\n"
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="Cannot activate test environment",
    ):
        source_environment(
            base={},
            sources=(
                broken,
            ),
            cwd=tmp_path,
            activation_label="test environment",
        )
