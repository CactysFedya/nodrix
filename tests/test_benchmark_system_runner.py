from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from pathlib import Path


from nodrix.benchmark_measured_runs import (
    CanonicalBenchmarkRunRequest,
    execute_canonical_benchmark_runs,
)
from nodrix.benchmark_system_runner import (
    CanonicalSystemBenchmarkRunner,
    CanonicalSystemBenchmarkWorkload,
)
from nodrix.benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from nodrix.run_session import (
    RunStore,
)
from nodrix.system import (
    BackendCapabilities,
    BackendContext,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    ExecutionBackend,
    ExecutionTiming,
    Graph,
    NodeInstance,
    PreparedExecution,
    SystemModel,
    SystemOrchestrator,
    Target,
    plan_system,
)
from nodrix.system.canonical import (
    system_plan_record,
)


NOW = datetime(
    2026,
    8,
    21,
    8,
    0,
    0,
    tzinfo=timezone.utc,
)


def _clock() -> datetime:
    return NOW


def _system() -> SystemModel:
    return SystemModel(
        name="benchmark-runner-system",
        targets=(
            Target(
                name="host",
                kind="host",
                properties={
                    "backend": "local",
                },
            ),
        ),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                        target="host",
                    ),
                ),
            ),
        ),
    )


def _plan(
    system: SystemModel,
):
    return system_plan_record(
        plan_system(
            system
        )
    )


class CompletingBackend(
    ExecutionBackend
):
    def __init__(
        self,
        *,
        terminal_state: (
            BackendExecutionState
        ) = (
            BackendExecutionState.COMPLETED
        ),
        complete_after: int = 2,
        duration_seconds: float = 0.125,
        fail_inspection: bool = False,
    ) -> None:
        super().__init__(
            "local",
            capabilities=BackendCapabilities(
                target_kinds={
                    "host",
                },
            ),
        )

        self.terminal_state = (
            terminal_state
        )

        self.complete_after = (
            complete_after
        )

        self.duration_seconds = (
            duration_seconds
        )

        self.fail_inspection = (
            fail_inspection
        )

        self.inspect_count = 0
        self.stop_count = 0

    def _prepare(
        self,
        context: BackendContext,
    ) -> PreparedExecution:
        return PreparedExecution(
            backend=self.backend_id,
            context=context,
        )

    def _start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id="backend-execution",
            prepared=prepared,
        )

    def _inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        self.inspect_count += 1

        if self.fail_inspection:
            raise RuntimeError(
                "synthetic inspection failure"
            )

        if (
            self.inspect_count
            < self.complete_after
        ):
            state = (
                BackendExecutionState.RUNNING
            )

            timing = None
        else:
            state = self.terminal_state

            timing = ExecutionTiming(
                self.duration_seconds
            )

        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=(
                handle.execution_id
            ),
            state=state,
            timing=timing,
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        del timeout_seconds

        self.stop_count += 1

        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=(
                handle.execution_id
            ),
            state=(
                BackendExecutionState.STOPPED
            ),
            timing=ExecutionTiming(
                self.duration_seconds
            ),
        )


def _workload(
    backend: CompletingBackend,
) -> CanonicalSystemBenchmarkWorkload:
    system = _system()

    return (
        CanonicalSystemBenchmarkWorkload(
            system_definition=system,
            plan=_plan(
                system
            ),
            orchestrator=(
                SystemOrchestrator(
                    {
                        (
                            "host",
                            "local",
                        ): backend,
                    }
                )
            ),
        )
    )


def _request(
    tmp_path: Path,
    *,
    repeat: int = 1,
    warmup: int = 0,
    phase: str = "measured",
    iteration: int = 0,
) -> CanonicalBenchmarkRunRequest:
    source = (
        tmp_path
        / "system.yaml"
    )

    source.write_text(
        "{}\n",
        encoding="utf-8",
    )

    variant = BenchmarkVariant(
        "default"
    )

    plan = BenchmarkPlan(
        pipeline=source,
        repeat=repeat,
        warmup=warmup,
        variants=(
            variant,
        ),
    )

    return CanonicalBenchmarkRunRequest(
        plan=plan,
        variant=variant,
        phase=phase,
        iteration=iteration,
    )


def test_runner_returns_persisted_canonical_run_with_measured_timing(
    tmp_path,
) -> None:
    backend = CompletingBackend()

    sleeps: list[
        float
    ] = []

    store = RunStore(
        tmp_path
        / "runs",
        clock=_clock,
    )

    runner = (
        CanonicalSystemBenchmarkRunner(
            workload_resolver=(
                lambda request: _workload(
                    backend
                )
            ),
            run_store=store,
            sleeper=sleeps.append,
            clock=_clock,
        )
    )

    bundle = runner(
        _request(
            tmp_path
        )
    )

    assert (
        bundle.session.plan_id
        == _workload(
            CompletingBackend()
        ).plan.plan_id
    )

    execution = bundle.run[
        "execution"
    ]

    assert (
        execution[
            "state"
        ]
        == "completed"
    )

    assert (
        execution[
            "details"
        ][
            "execution_timing"
        ][
            "duration_seconds"
        ]
        == 0.125
    )

    assert (
        bundle.session.directory
        / "run.json"
    ).is_file()

    # Immediate first inspection, then one 1 ms wait before terminal state.
    assert sleeps == [
        0.001
    ]


def test_runner_returns_failed_run_as_evidence(
    tmp_path,
) -> None:
    backend = CompletingBackend(
        terminal_state=(
            BackendExecutionState.FAILED
        ),
        complete_after=1,
        duration_seconds=0.2,
    )

    runner = (
        CanonicalSystemBenchmarkRunner(
            workload_resolver=(
                lambda request: _workload(
                    backend
                )
            ),
            run_store=RunStore(
                tmp_path / "runs",
                clock=_clock,
            ),
            sleeper=lambda delay: None,
            clock=_clock,
        )
    )

    bundle = runner(
        _request(
            tmp_path
        )
    )

    execution = bundle.run[
        "execution"
    ]

    assert (
        execution[
            "state"
        ]
        == "failed"
    )

    assert (
        execution[
            "successful"
        ]
        is False
    )

    assert (
        execution[
            "details"
        ][
            "execution_timing"
        ][
            "duration_seconds"
        ]
        == 0.2
    )


def test_runner_persists_orchestrated_inspection_failure_as_failed_run(
    tmp_path,
) -> None:
    backend = CompletingBackend(
        fail_inspection=True
    )

    runner = (
        CanonicalSystemBenchmarkRunner(
            workload_resolver=(
                lambda request: _workload(
                    backend
                )
            ),
            run_store=RunStore(
                tmp_path / "runs",
                clock=_clock,
            ),
            sleeper=lambda delay: None,
            clock=_clock,
        )
    )

    bundle = runner(
        _request(
            tmp_path
        )
    )

    execution = bundle.run[
        "execution"
    ]

    # Backend inspection failures are deliberately normalized by the System
    # orchestrator into terminal FAILED execution evidence. They are execution
    # outcomes, not control-plane exceptions from the Benchmark runner.
    assert (
        execution[
            "state"
        ]
        == "failed"
    )

    assert (
        execution[
            "successful"
        ]
        is False
    )

    details = execution[
        "details"
    ]

    assert (
        details[
            "message"
        ]
        == "synthetic inspection failure"
    )

    status_details = details[
        "status_details"
    ]

    assert (
        status_details[
            "exception_type"
        ]
        == "RuntimeError"
    )

    assert (
        status_details[
            "failure_source"
        ]
        == "scope"
    )

    assert (
        status_details[
            "scope"
        ]
        == "host:local"
    )

    assert (
        status_details[
            "backend"
        ]
        == "local"
    )

    # The execution is already terminal FAILED. Calling stop here would alter
    # lifecycle semantics instead of merely recovering from a runner failure.
    assert (
        backend.stop_count
        == 0
    )

    assert (
        bundle.session.directory
        / "run.json"
    ).is_file()


def test_runner_is_directly_compatible_with_measured_run_coordinator(
    tmp_path,
) -> None:
    source = (
        tmp_path
        / "system.yaml"
    )

    source.write_text(
        "{}\n",
        encoding="utf-8",
    )

    variant = BenchmarkVariant(
        "default"
    )

    plan = BenchmarkPlan(
        pipeline=source,
        repeat=2,
        warmup=1,
        variants=(
            variant,
        ),
    )

    backends: list[
        CompletingBackend
    ] = []

    def resolve(
        request: CanonicalBenchmarkRunRequest,
    ) -> CanonicalSystemBenchmarkWorkload:
        del request

        backend = CompletingBackend(
            complete_after=1,
        )

        backends.append(
            backend
        )

        return _workload(
            backend
        )

    runner = (
        CanonicalSystemBenchmarkRunner(
            workload_resolver=resolve,
            run_store=RunStore(
                tmp_path / "runs",
                clock=_clock,
            ),
            sleeper=lambda delay: None,
            clock=_clock,
        )
    )

    runs = (
        execute_canonical_benchmark_runs(
            plan,
            run_callable=runner,
        )
    )

    assert len(
        runs.variants
    ) == 1

    result = runs.variants[
        0
    ]

    assert len(
        result.warmup
    ) == 1

    assert len(
        result.measured
    ) == 2

    all_ids = (
        result.warmup_run_ids
        + result.measured_run_ids
    )

    assert len(
        set(
            all_ids
        )
    ) == 3

    assert len(
        backends
    ) == 3

    # Warmup and measured executions use exactly the same ordinary Run path.
    for bundle in (
        *result.warmup,
        *result.measured,
    ):
        assert (
            bundle.run[
                "execution"
            ][
                "details"
            ][
                "execution_timing"
            ][
                "source"
            ]
            == "backend"
        )
