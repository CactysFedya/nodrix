"""Canonical System execution bridge for measured Benchmark Runs.

This module deliberately does not resolve YAML, project profiles or Benchmark
variant authoring syntax.  It executes an already-resolved canonical System
workload as one ordinary persistent Run and returns that Run as canonical
historical evidence.

Benchmark coordination, warmup/measured classification, aggregation and
BenchmarkResult materialization belong to higher layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import time
from typing import Callable

from .benchmark_measured_runs import (
    CanonicalBenchmarkRunRequest,
)
from .execution_policy import (
    ExecutionPolicy,
)
from .model import (
    SYSTEM_EXECUTION,
    PlanRecord,
)
from .run_bundle import (
    CanonicalRunBundle,
    load_canonical_run_bundle,
)
from .run_session import (
    RunStore,
)
from .system.canonical_runtime import (
    inspect_canonical_system_execution,
    start_canonical_system_execution,
    stop_canonical_system_execution,
)
from .system.execution_context import (
    SystemExecutionContext,
)
from .system.model import (
    SystemModel,
)
from .system.orchestration import (
    SystemOrchestrator,
)


Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


class CanonicalSystemBenchmarkRunError(
    RuntimeError
):
    """Canonical measured System Run could not be completed or recovered."""


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalSystemBenchmarkWorkload:
    """One exact, already-resolved System execution workload.

    ``orchestrator`` is execution machinery, not workload identity.
    Definition, Plan, execution context and effective ExecutionPolicy are the
    reproducible semantics persisted by the canonical Run boundary.
    """

    system_definition: SystemModel
    plan: PlanRecord
    orchestrator: SystemOrchestrator
    execution_context: (
        SystemExecutionContext | None
    ) = None
    execution_policy: (
        ExecutionPolicy | None
    ) = None

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.system_definition,
            SystemModel,
        ):
            raise TypeError(
                "system_definition must be "
                "a SystemModel"
            )

        if not isinstance(
            self.plan,
            PlanRecord,
        ):
            raise TypeError(
                "plan must be a PlanRecord"
            )

        if (
            self.plan.kind
            != SYSTEM_EXECUTION
        ):
            raise ValueError(
                "canonical System Benchmark workload "
                "requires a system execution PlanRecord"
            )

        if not isinstance(
            self.orchestrator,
            SystemOrchestrator,
        ):
            raise TypeError(
                "orchestrator must be "
                "a SystemOrchestrator"
            )

        if (
            self.execution_context
            is not None
            and not isinstance(
                self.execution_context,
                SystemExecutionContext,
            )
        ):
            raise TypeError(
                "execution_context must be a "
                "SystemExecutionContext or None"
            )

        if (
            self.execution_policy
            is not None
            and not isinstance(
                self.execution_policy,
                ExecutionPolicy,
            )
        ):
            raise TypeError(
                "execution_policy must be an "
                "ExecutionPolicy or None"
            )


CanonicalSystemBenchmarkWorkloadResolver = Callable[
    [
        CanonicalBenchmarkRunRequest,
    ],
    CanonicalSystemBenchmarkWorkload,
]


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _positive_seconds(
    value: float,
    *,
    field_name: str,
) -> float:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            (
                int,
                float,
            ),
        )
    ):
        raise TypeError(
            f"{field_name} must be a real number"
        )

    result = float(
        value
    )

    if (
        not math.isfinite(
            result
        )
        or result <= 0.0
    ):
        raise ValueError(
            f"{field_name} must be finite "
            "and greater than zero"
        )

    return result


def _poll_multiplier(
    value: float,
) -> float:
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            (
                int,
                float,
            ),
        )
    ):
        raise TypeError(
            "poll_multiplier must be "
            "a real number"
        )

    result = float(
        value
    )

    if (
        not math.isfinite(
            result
        )
        or result < 1.0
    ):
        raise ValueError(
            "poll_multiplier must be finite "
            "and at least 1.0"
        )

    return result


class CanonicalSystemBenchmarkRunner:
    """Execute resolved Benchmark workloads as ordinary canonical System Runs.

    The runner intentionally starts with an immediate terminal inspection and
    then uses bounded exponential polling.  This keeps short benchmark
    workloads responsive without busy-spinning on long-running Systems.

    Polling latency is control-plane latency only.  Benchmark duration comes
    from backend ``ExecutionTiming`` persisted in the Run, never from this
    polling loop.
    """

    def __init__(
        self,
        *,
        workload_resolver: (
            CanonicalSystemBenchmarkWorkloadResolver
        ),
        run_store: RunStore,
        poll_initial_seconds: float = 0.001,
        poll_max_seconds: float = 0.050,
        poll_multiplier: float = 2.0,
        sleeper: Sleeper = time.sleep,
        clock: Clock = _utc_now,
    ) -> None:
        if not callable(
            workload_resolver
        ):
            raise TypeError(
                "workload_resolver must be callable"
            )

        if not isinstance(
            run_store,
            RunStore,
        ):
            raise TypeError(
                "run_store must be a RunStore"
            )

        if not callable(
            sleeper
        ):
            raise TypeError(
                "sleeper must be callable"
            )

        if not callable(
            clock
        ):
            raise TypeError(
                "clock must be callable"
            )

        initial = _positive_seconds(
            poll_initial_seconds,
            field_name=(
                "poll_initial_seconds"
            ),
        )

        maximum = _positive_seconds(
            poll_max_seconds,
            field_name=(
                "poll_max_seconds"
            ),
        )

        if maximum < initial:
            raise ValueError(
                "poll_max_seconds must be "
                "greater than or equal to "
                "poll_initial_seconds"
            )

        self._workload_resolver = (
            workload_resolver
        )

        self._run_store = run_store

        self._poll_initial_seconds = (
            initial
        )

        self._poll_max_seconds = (
            maximum
        )

        self._poll_multiplier = (
            _poll_multiplier(
                poll_multiplier
            )
        )

        self._sleeper = sleeper
        self._clock = clock

    @property
    def workload_resolver(
        self,
    ) -> object:
        """Return the exact workload resolver used by this runner.

        The canonical Benchmark coordinator uses this same resolver to derive
        workload-set identity before execution, preventing Plan provenance
        from diverging from the workloads that actual Runs execute.
        """

        return self._workload_resolver

    def __call__(
        self,
        request: CanonicalBenchmarkRunRequest,
    ) -> CanonicalRunBundle:
        if not isinstance(
            request,
            CanonicalBenchmarkRunRequest,
        ):
            raise TypeError(
                "request must be a "
                "CanonicalBenchmarkRunRequest"
            )

        workload = (
            self._workload_resolver(
                request
            )
        )

        if not isinstance(
            workload,
            CanonicalSystemBenchmarkWorkload,
        ):
            raise TypeError(
                "workload_resolver must return "
                "CanonicalSystemBenchmarkWorkload"
            )

        execution = (
            start_canonical_system_execution(
                workload.orchestrator,
                workload.plan,
                system_definition=(
                    workload.system_definition
                ),
                execution_context=(
                    workload.execution_context
                ),
                execution_policy=(
                    workload.execution_policy
                ),
                run_store=(
                    self._run_store
                ),
                clock=self._clock,
            )
        )

        delay = (
            self._poll_initial_seconds
        )

        try:
            while True:
                record = (
                    inspect_canonical_system_execution(
                        workload.orchestrator,
                        execution,
                        clock=self._clock,
                    )
                )

                if record.terminal:
                    break

                self._sleeper(
                    delay
                )

                delay = min(
                    self._poll_max_seconds,
                    (
                        delay
                        * self._poll_multiplier
                    ),
                )

        except BaseException as exc:
            # Do not leak a live System when benchmark coordination is
            # interrupted or inspection fails.  Preserve the original error;
            # cleanup failure is secondary diagnostic evidence.
            try:
                stop_canonical_system_execution(
                    workload.orchestrator,
                    execution,
                    clock=self._clock,
                )
            except BaseException as stop_exc:
                exc.add_note(
                    "canonical Benchmark cleanup "
                    "also failed: "
                    f"{type(stop_exc).__name__}: "
                    f"{stop_exc}"
                )

            raise

        session = (
            execution.run_session
        )

        if session is None:
            raise CanonicalSystemBenchmarkRunError(
                "persistent canonical Benchmark "
                "execution completed without "
                "a RunSession"
            )

        if not (
            execution.final_run_recorded
        ):
            persistence_errors = (
                execution
                .run_record_persistence_errors
            )

            suffix = (
                ": "
                + "; ".join(
                    persistence_errors
                )
                if persistence_errors
                else ""
            )

            raise CanonicalSystemBenchmarkRunError(
                "canonical Benchmark execution "
                "reached a terminal state but "
                "run.json was not published"
                + suffix
            )

        try:
            bundle = (
                load_canonical_run_bundle(
                    session.directory
                )
            )
        except Exception as exc:
            raise (
                CanonicalSystemBenchmarkRunError(
                    "failed to reopen completed "
                    "canonical Benchmark Run "
                    f"{session.run_id!r}"
                )
            ) from exc

        if (
            bundle.session.run_id
            != session.run_id
        ):
            raise CanonicalSystemBenchmarkRunError(
                "reopened canonical Benchmark Run "
                "has a different Run identity"
            )

        if (
            bundle.session.plan_id
            != workload.plan.plan_id
        ):
            raise CanonicalSystemBenchmarkRunError(
                "reopened canonical Benchmark Run "
                "has a different Plan identity"
            )

        return bundle


__all__ = [
    "CanonicalSystemBenchmarkRunError",
    "CanonicalSystemBenchmarkRunner",
    "CanonicalSystemBenchmarkWorkload",
    "CanonicalSystemBenchmarkWorkloadResolver",
]
