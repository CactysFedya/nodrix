"""Canonical control-plane policy applied around one Nodrix Execution.

ExecutionPolicy belongs to execution/Run policy, not to a System Definition.

It deliberately does not change the semantic contents of an exact PlanRecord.
Anything that changes what is actually executed -- graph topology, dependency
semantics, restart behavior, resource placement, queue behavior, or other
domain execution semantics -- must be resolved by planning and represented in
the exact domain Plan.

This policy instead owns cross-domain control-plane behavior surrounding that
execution.

Initial v1 composition:

    ExecutionPolicy
        -> RunEnvironmentPolicy
        -> RunLogPolicy

Lifecycle Events are mandatory historical evidence and therefore are not an
optional policy switch.

Metrics and Artifacts remain separate canonical entities and are intentionally
not represented as logs.

Retention is storage lifecycle policy and is not execution semantics.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)

from nodrix.run_environment import (
    RunEnvironmentPolicy,
)
from nodrix.run_logs import (
    RunLogPolicy,
)


@dataclass(
    frozen=True,
    slots=True,
)
class ExecutionPolicy:
    """Cross-domain control-plane policy for one execution.

    The same type is used regardless of OperationKind.  ``run``, ``test``,
    ``benchmark``, ``profile``, ``diagnose`` and custom operations must not
    create parallel policy hierarchies.

    ``environment`` controls immutable environment provenance capture.

    ``logs`` controls optional bounded diagnostic logging.

    Neither field changes the resolved semantic Plan that the executor receives.
    """

    environment: RunEnvironmentPolicy = field(
        default_factory=RunEnvironmentPolicy
    )
    logs: RunLogPolicy = field(
        default_factory=RunLogPolicy
    )

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.environment,
            RunEnvironmentPolicy,
        ):
            raise TypeError(
                "environment must be a "
                "RunEnvironmentPolicy"
            )

        if not isinstance(
            self.logs,
            RunLogPolicy,
        ):
            raise TypeError(
                "logs must be a RunLogPolicy"
            )


__all__ = [
    "ExecutionPolicy",
]
