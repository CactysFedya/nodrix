"""Local execution adapter for canonical System plans.

This module is deliberately separate from the backend-neutral
``system_execution_frontend``.  It selects the current LocalBackend only for
scopes that explicitly request backend ``local``.

Other backend scopes remain unbound so SystemOrchestrator can surface canonical
ORCH101 diagnostics.  There is no fallback from another backend to local.
"""

from __future__ import annotations

from pathlib import Path

from .system import (
    ExecutionBackend,
    ExecutionScope,
    LocalBackend,
    SystemOrchestrator,
)
from .system_execution_frontend import (
    SystemBackendFactory,
    SystemExecutionPlanInput,
    build_system_orchestrator,
)


def local_backend_factory(
    *,
    project: str | Path | None = None,
    working_directory: str | Path | None = None,
    run_root: str | Path | None = None,
    stop_timeout_seconds: float = 10.0,
) -> SystemBackendFactory:
    """Create one reusable explicit local-scope backend factory."""

    if (
        isinstance(
            stop_timeout_seconds,
            bool,
        )
        or not isinstance(
            stop_timeout_seconds,
            (
                int,
                float,
            ),
        )
    ):
        raise TypeError(
            "stop_timeout_seconds must be "
            "a real number"
        )

    timeout = float(
        stop_timeout_seconds
    )

    if timeout < 0.0:
        raise ValueError(
            "stop_timeout_seconds cannot be negative"
        )

    project_path = (
        None
        if project is None
        else (
            Path(
                project
            )
            .expanduser()
            .resolve()
        )
    )

    working_path = (
        None
        if working_directory is None
        else (
            Path(
                working_directory
            )
            .expanduser()
            .resolve()
        )
    )

    run_path = (
        None
        if run_root is None
        else (
            Path(
                run_root
            )
            .expanduser()
            .resolve()
        )
    )

    def resolve(
        scope: ExecutionScope,
    ) -> ExecutionBackend | None:
        if not isinstance(
            scope,
            ExecutionScope,
        ):
            raise TypeError(
                "scope must be an ExecutionScope"
            )

        if scope.backend != "local":
            return None

        return LocalBackend(
            project=project_path,
            working_directory=working_path,
            run_root=run_path,
            stop_timeout_seconds=timeout,
            scope_name=scope.target,
        )

    return resolve


def build_local_system_orchestrator(
    value: SystemExecutionPlanInput,
    *,
    project: str | Path | None = None,
    working_directory: str | Path | None = None,
    run_root: str | Path | None = None,
    stop_timeout_seconds: float = 10.0,
) -> SystemOrchestrator:
    """Build an orchestrator with explicit bindings for local scopes only."""

    return build_system_orchestrator(
        value,
        backend_factory=local_backend_factory(
            project=project,
            working_directory=(
                working_directory
            ),
            run_root=run_root,
            stop_timeout_seconds=(
                stop_timeout_seconds
            ),
        ),
    )


__all__ = [
    "build_local_system_orchestrator",
    "local_backend_factory",
]
