"""Architecture invariants for the unified Nodrix operation model."""

from __future__ import annotations

import inspect

import nodrix.benchmark_executor as benchmark_executor
import nodrix.cli_operation_commands as operation_commands
import nodrix.optimization_executor as optimization_executor
import nodrix.workflow_executor as workflow_executor


def test_domain_executors_do_not_own_durable_history() -> None:
    """Executors produce Executions; operation boundaries persist Runs."""

    for module in (
        workflow_executor,
        benchmark_executor,
        optimization_executor,
    ):
        source = inspect.getsource(
            module
        )

        assert "persist_execution(" not in source
        assert "record_run(" not in source
        assert "write_run_document(" not in source


def test_operation_cli_does_not_bypass_canonical_services() -> None:
    """CLI must enter execution through canonical operation services."""

    source = inspect.getsource(
        operation_commands
    )

    forbidden = (
        "run_workflow(",
        "run_benchmark_suite(",
        "write_optimization_bundle(",
        "optimization_spec(",
        "select_optimization_variant(",
    )

    for call in forbidden:
        assert call not in source
