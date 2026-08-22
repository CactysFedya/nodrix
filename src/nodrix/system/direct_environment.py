"""Physical execution environment for direct System preparation.

This module contains backend-owned physical execution inputs only.  It is not
part of the System Definition or SystemExecutionPlan and does not introduce a
second semantic execution model.

The environment currently carries only the base directory used to resolve
relative implementation references.  Runtime policies such as process-memory
pools belong to canonical execution semantics and must not be invented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(
    frozen=True,
    slots=True,
)
class DirectExecutionEnvironment:
    """Physical filesystem context supplied by an execution backend."""

    base_dir: Path

    def __post_init__(self) -> None:
        path = Path(
            self.base_dir
        ).expanduser()

        if not path.is_absolute():
            raise ValueError(
                "DirectExecutionEnvironment.base_dir "
                "must be an absolute path"
            )

        object.__setattr__(
            self,
            "base_dir",
            path.resolve(),
        )


__all__ = [
    "DirectExecutionEnvironment",
]
