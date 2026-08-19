"""Canonical observability profiles for one Nodrix Execution.

Observability profiles are execution-time policy presets.

They are deliberately distinct from:

- Project Profile (``nodrix.profile/v1``);
- legacy Pipeline RuntimePreset/profile;
- OperationKind.PROFILE.

A profile resolves to one ordinary ``ExecutionPolicy`` before execution.
The profile name itself is not System Definition or Plan semantics.
"""

from __future__ import annotations

from enum import Enum

from .execution_policy import (
    ExecutionPolicy,
)
from .run_logs import (
    RunLogPolicy,
)
from .run_metric_policy import (
    RunMetricPolicy,
)


class ObservabilityProfileName(
    str,
    Enum,
):
    """Stable names of built-in observability policy presets."""

    MINIMAL = "minimal"
    STANDARD = "standard"
    DEBUG = "debug"
    BENCHMARK = "benchmark"
    CUSTOM = "custom"


def _profile_name(
    value: ObservabilityProfileName | str,
) -> ObservabilityProfileName:
    if isinstance(
        value,
        ObservabilityProfileName,
    ):
        return value

    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            "observability profile must be "
            "an ObservabilityProfileName or string"
        )

    canonical = (
        value
        .strip()
        .lower()
    )

    try:
        return ObservabilityProfileName(
            canonical
        )
    except ValueError as exc:
        supported = ", ".join(
            item.value
            for item
            in ObservabilityProfileName
        )

        raise ValueError(
            "unsupported observability profile "
            f"{value!r}; expected one of: "
            f"{supported}"
        ) from exc


def resolve_observability_profile(
    profile: ObservabilityProfileName | str,
    *,
    custom_policy: ExecutionPolicy | None = None,
) -> ExecutionPolicy:
    """Resolve one profile into an exact canonical ExecutionPolicy.

    Predefined profiles are deterministic and do not accept overrides.
    ``custom`` requires the caller to supply the exact ExecutionPolicy.

    Critical lifecycle Events are intentionally absent from this API because
    they are mandatory historical evidence and cannot be disabled by an
    observability profile.
    """

    name = _profile_name(
        profile
    )

    if (
        name
        is ObservabilityProfileName.CUSTOM
    ):
        if custom_policy is None:
            raise ValueError(
                "custom observability profile "
                "requires custom_policy"
            )

        if not isinstance(
            custom_policy,
            ExecutionPolicy,
        ):
            raise TypeError(
                "custom_policy must be an "
                "ExecutionPolicy or None"
            )

        return custom_policy

    if custom_policy is not None:
        raise ValueError(
            "custom_policy is only valid with "
            "the custom observability profile"
        )

    if (
        name
        is ObservabilityProfileName.MINIMAL
    ):
        return ExecutionPolicy()

    if (
        name
        is ObservabilityProfileName.STANDARD
    ):
        return ExecutionPolicy(
            logs=RunLogPolicy(
                enabled=True,
                min_level="warning",
            ),
            metrics=RunMetricPolicy(),
        )

    if (
        name
        is ObservabilityProfileName.DEBUG
    ):
        return ExecutionPolicy(
            logs=RunLogPolicy(
                enabled=True,
                min_level="debug",
                max_bytes=16 * 1024 * 1024,
                max_category_bytes=4 * 1024 * 1024,
                max_record_bytes=64 * 1024,
                overflow="drop",
            ),
            metrics=RunMetricPolicy(
                max_records=250_000,
                max_bytes=16 * 1024 * 1024,
                max_record_bytes=64 * 1024,
                overflow="drop",
            ),
        )

    if (
        name
        is ObservabilityProfileName.BENCHMARK
    ):
        return ExecutionPolicy(
            logs=RunLogPolicy(
                enabled=False,
            ),
            metrics=RunMetricPolicy(
                max_records=500_000,
                max_bytes=32 * 1024 * 1024,
                max_record_bytes=64 * 1024,
                overflow="drop",
            ),
        )

    raise AssertionError(
        f"unhandled observability profile {name!r}"
    )


__all__ = [
    "ObservabilityProfileName",
    "resolve_observability_profile",
]
