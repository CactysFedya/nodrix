from __future__ import annotations

from dataclasses import (
    MISSING,
    fields,
)
from inspect import (
    Parameter,
    signature,
)

from nodrix.executor_contract import (
    PlanExecutor,
)
from nodrix.extension_dispatcher import (
    ExtensionDispatcher,
)
from nodrix.model.executions import (
    ExecutionRecord,
)
from nodrix.model.operations import (
    BENCHMARK,
    BUILD,
    CALIBRATE,
    CLEANUP,
    DIAGNOSE,
    EXPORT,
    OPTIMIZE,
    PACKAGE,
    PREPARE,
    PROFILE,
    RUN,
    TEST,
    VALIDATE,
    Operation,
    OperationKind,
)
from nodrix.model.plans import (
    PlanRecord,
)
from nodrix.model.runs import (
    RunRecord,
)
from nodrix.planner_contract import (
    OperationPlanner,
)


def _field_map(
    model,
):
    return {
        item.name: item
        for item in fields(model)
    }


def test_opr001_operation_is_intent_and_revision_may_be_unresolved() -> None:
    operation_fields = _field_map(
        Operation
    )

    assert {
        "kind",
        "subject",
        "subject_revision",
        "parameters",
    }.issubset(
        operation_fields
    )

    revision = operation_fields[
        "subject_revision"
    ]

    assert revision.default is None

    forbidden = {
        "execution_id",
        "executor",
        "state",
        "started_at",
        "finished_at",
        "run_id",
    }

    assert forbidden.isdisjoint(
        operation_fields
    )


def test_opr002_plan_must_pin_exact_subject_revision() -> None:
    plan_fields = _field_map(
        PlanRecord
    )

    assert {
        "plan_id",
        "kind",
        "operation",
        "subject_revision",
        "payload",
    }.issubset(
        plan_fields
    )

    revision = plan_fields[
        "subject_revision"
    ]

    assert revision.default is MISSING
    assert revision.default_factory is MISSING


def test_opr003_execution_is_factual_result_of_exact_plan() -> None:
    execution_fields = _field_map(
        ExecutionRecord
    )

    assert {
        "execution_id",
        "plan",
        "executor",
        "state",
        "started_at",
        "finished_at",
        "details",
    }.issubset(
        execution_fields
    )

    # Operation identity and resolved provenance come through PlanRecord.
    # They must not become a second mutable copy on ExecutionRecord.
    assert "operation" not in execution_fields
    assert "operation_kind" not in execution_fields
    assert "subject_revision" not in execution_fields

    assert isinstance(
        ExecutionRecord.subject_revision,
        property,
    )


def test_opr004_run_wraps_execution_without_operation_specific_model() -> None:
    run_fields = _field_map(
        RunRecord
    )

    assert {
        "run_id",
        "execution",
        "summary",
        "metadata",
    }.issubset(
        run_fields
    )

    assert "operation" not in run_fields
    assert "operation_kind" not in run_fields
    assert "plan" not in run_fields
    assert "subject_revision" not in run_fields

    assert isinstance(
        RunRecord.subject_revision,
        property,
    )


def test_opr005_builtin_operation_kinds_share_one_extensible_type() -> None:
    builtins = {
        PREPARE: "prepare",
        BUILD: "build",
        TEST: "test",
        VALIDATE: "validate",
        RUN: "run",
        PROFILE: "profile",
        BENCHMARK: "benchmark",
        OPTIMIZE: "optimize",
        DIAGNOSE: "diagnose",
        CALIBRATE: "calibrate",
        EXPORT: "export",
        PACKAGE: "package",
        CLEANUP: "cleanup",
    }

    for operation_kind, expected in builtins.items():
        assert isinstance(
            operation_kind,
            OperationKind,
        )
        assert str(
            operation_kind
        ) == expected

    custom = OperationKind(
        "acme.hardware-check"
    )

    assert str(custom) == (
        "acme.hardware-check"
    )


def test_opr006_planner_resolves_operation_with_explicit_context() -> None:
    parameters = signature(
        OperationPlanner.plan
    ).parameters

    assert tuple(parameters) == (
        "self",
        "operation",
        "context",
    )

    assert (
        parameters["context"].kind
        is Parameter.KEYWORD_ONLY
    )


def test_opr007_executor_accepts_only_exact_plan_record() -> None:
    parameters = signature(
        PlanExecutor.execute
    ).parameters

    assert tuple(parameters) == (
        "self",
        "plan",
    )

    assert (
        parameters["plan"].kind
        is Parameter.POSITIONAL_OR_KEYWORD
    )


def test_opr008_dispatcher_keeps_planning_and_execution_separate() -> None:
    plan_parameters = signature(
        ExtensionDispatcher.plan
    ).parameters

    execute_parameters = signature(
        ExtensionDispatcher.execute
    ).parameters

    dispatch_parameters = signature(
        ExtensionDispatcher.dispatch
    ).parameters

    assert tuple(
        plan_parameters
    ) == (
        "self",
        "operation",
        "context",
    )

    assert tuple(
        execute_parameters
    ) == (
        "self",
        "plan",
    )

    assert tuple(
        dispatch_parameters
    ) == (
        "self",
        "operation",
        "context",
    )

    assert (
        dispatch_parameters["context"].kind
        is Parameter.KEYWORD_ONLY
    )


def test_opr009_core_has_no_operation_specific_run_types() -> None:
    import nodrix.model.executions as execution_model
    import nodrix.model.runs as run_model

    forbidden_execution_types = (
        "BenchmarkExecutionRecord",
        "TestExecutionRecord",
        "ProfileExecutionRecord",
        "DiagnosticsExecutionRecord",
    )

    forbidden_run_types = (
        "BenchmarkRunRecord",
        "TestRunRecord",
        "ProfileRunRecord",
        "DiagnosticsRunRecord",
    )

    for name in forbidden_execution_types:
        assert not hasattr(
            execution_model,
            name,
        )

    for name in forbidden_run_types:
        assert not hasattr(
            run_model,
            name,
        )
