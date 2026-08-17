"""Pipeline-neutral execution environment materialization.

This module resolves shell source files into an explicit environment mapping.
It never mutates ``os.environ``.

Higher-level project, workflow, and System execution layers decide which
variables are explicit and whether they must be re-applied after shell
activation.
"""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
from typing import Mapping, Sequence


def source_environment(
    *,
    base: Mapping[str, str],
    sources: Sequence[str | Path],
    cwd: str | Path,
    activation_label: str = "environment",
) -> dict[str, str]:
    """Source shell files into a copy of one explicit base environment."""

    root = Path(
        cwd
    ).expanduser().resolve()

    paths = tuple(
        Path(source)
        for source in sources
    )

    result = dict(
        base
    )

    if not paths:
        return result

    missing = [
        path
        for path in paths
        if not path.is_file()
    ]

    if missing:
        rendered = ", ".join(
            str(path)
            for path in missing
        )

        raise FileNotFoundError(
            "Environment source files not found: "
            f"{rendered}"
        )

    commands = [
        "set -a"
    ]

    commands.extend(
        f"source {shlex.quote(str(path))}"
        for path in paths
    )

    commands.append(
        "env -0"
    )

    completed = subprocess.run(
        [
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-c",
            "; ".join(commands),
        ],
        cwd=root,
        env=result,
        check=False,
        capture_output=True,
    )

    if completed.returncode:
        detail = completed.stderr.decode(
            errors="replace"
        ).strip()

        raise RuntimeError(
            f"Cannot activate {activation_label}: "
            f"{detail}"
        )

    for item in completed.stdout.split(
        b"\0"
    ):
        if (
            not item
            or b"=" not in item
        ):
            continue

        key, value = item.split(
            b"=",
            1,
        )

        result[
            key.decode(
                errors="replace"
            )
        ] = value.decode(
            errors="replace"
        )

    return result


def materialize_environment(
    *,
    base: Mapping[str, str],
    variables: Mapping[str, str],
    sources: Sequence[str | Path],
    cwd: str | Path,
    activation_label: str = "environment",
) -> dict[str, str]:
    """Materialize sources while preserving explicit variable precedence."""

    explicit = {
        str(key): str(value)
        for key, value in variables.items()
    }

    initial = dict(
        base
    )

    initial.update(
        explicit
    )

    resolved = source_environment(
        base=initial,
        sources=sources,
        cwd=cwd,
        activation_label=activation_label,
    )

    # Explicit resolved values win over values exported by sourced scripts.
    resolved.update(
        explicit
    )

    return resolved


__all__ = [
    "materialize_environment",
    "source_environment",
]
