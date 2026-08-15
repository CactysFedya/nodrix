"""Canonical cross-domain object model for Nodrix."""

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

__all__ = [
    "BENCHMARK",
    "BUILD",
    "CALIBRATE",
    "CLEANUP",
    "DIAGNOSE",
    "EXPORT",
    "EntityRef",
    "Operation",
    "OperationKind",
    "PACKAGE",
    "PROFILE",
    "RUN",
    "RevisionRef",
    "TEST",
    "VALIDATE",
]
