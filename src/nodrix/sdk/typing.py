"""Public typing primitives for the simplified SDK."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

T = TypeVar("T")


class Input(Generic[T]):
    """Explicitly mark an annotation as a pipeline input port."""


class Param(Generic[T]):
    """Explicitly mark an annotation as a configuration parameter."""


class Resource(Generic[T]):
    """Request a pipeline-scoped resource binding by argument name."""


class Outputs:
    """Lightweight named multi-output result.

    Subclasses declare annotated fields and may be constructed with keyword
    arguments without also applying ``@dataclass``.
    """

    def __init__(self, **values: Any) -> None:
        fields = getattr(type(self), "__annotations__", {})
        unknown = sorted(set(values) - set(fields))
        missing = sorted(set(fields) - set(values))
        if unknown:
            raise TypeError(f"Unknown output field(s): {', '.join(unknown)}")
        if missing:
            raise TypeError(f"Missing output field(s): {', '.join(missing)}")
        for name, value in values.items():
            setattr(self, name, value)


__all__ = ["Input", "Outputs", "Param", "Resource"]
