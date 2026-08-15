"""Canonical cross-domain object model for Nodrix."""

from .executions import ExecutionRecord, ExecutionState
from .identity import EntityRef, RevisionRef
from .operations import (
    BENCHMARK,
    BUILD,
    CALIBRATE,
    CLEANUP,
    DIAGNOSE,
    EXPORT,
    PACKAGE,
    PROFILE,
    RUN,
    TEST,
    VALIDATE,
    Operation,
    OperationKind,
)
from .plans import (
    SYSTEM_EXECUTION,
    WORKFLOW,
    PlanKind,
    PlanRecord,
)
from .runs import RunRecord

__all__ = [
    "BENCHMARK",
    "BUILD",
    "CALIBRATE",
    "CLEANUP",
    "DIAGNOSE",
    "EXPORT",
    "EntityRef",
    "ExecutionRecord",
    "ExecutionState",
    "Operation",
    "OperationKind",
    "PACKAGE",
    "PROFILE",
    "PlanKind",
    "PlanRecord",
    "RUN",
    "RevisionRef",
    "RunRecord",
    "SYSTEM_EXECUTION",
    "TEST",
    "VALIDATE",
    "WORKFLOW",
]
