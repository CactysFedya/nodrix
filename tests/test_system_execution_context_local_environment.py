from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from nodrix.system import (
    Graph,
    LocalBackend,
    NodeInstance,
    SystemModel,
    plan_system,
)
from nodrix.system.execution_context import (
    SystemExecutionContext,
)


def _system() -> SystemModel:
    return SystemModel(
        name="local-environment",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="worker",
                        uses="demo.worker",
                    ),
                ),
            ),
        ),
    )


class CaptureRuntime:
    def __init__(
        self,
        manifest: Any,
        manifest_path: Path,
        run_root: Path | None,
    ) -> None:
        self.manifest = manifest
        self.manifest_path = Path(
            manifest_path
        )
        self.run_root = run_root
        self.environment: dict[
            str,
            str,
        ] | None = None
        self.built = False

    def set_execution_environment(
        self,
        environment,
    ) -> None:
        self.environment = dict(
            environment
        )

    def build(self) -> None:
        assert (
            self.environment
            is not None
        )
        self.built = True


class LegacyRuntime:
    """Custom runtime without the new explicit-environment capability."""

    def __init__(
        self,
        manifest: Any,
        manifest_path: Path,
        run_root: Path | None,
    ) -> None:
        self.manifest = manifest
        self.manifest_path = Path(
            manifest_path
        )
        self.run_root = run_root
        self.built = False

    def build(self) -> None:
        self.built = True


def test_local_backend_materializes_execution_environment_before_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup = tmp_path / "setup.bash"

    setup.write_text(
        (
            'export SOURCE_ONLY="from-source"\n'
            'export PROFILE_VALUE="from-source"\n'
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "BASE_VALUE",
        "from-parent",
    )

    monkeypatch.delenv(
        "PROFILE_VALUE",
        raising=False,
    )

    monkeypatch.delenv(
        "SOURCE_ONLY",
        raising=False,
    )

    secret = (
        "alpha5c3b2-secret-value"
    )

    execution_context = (
        SystemExecutionContext(
            variables={
                "PROFILE_VALUE": "explicit",
                "SECRET_TOKEN": secret,
            },
            sources=(
                str(setup),
            ),
        )
    )

    plan = plan_system(
        _system(),
        execution_context=(
            execution_context
        ),
    )

    captured: dict[
        str,
        CaptureRuntime,
    ] = {}

    def factory(
        manifest,
        manifest_path,
        run_root,
    ):
        runtime = CaptureRuntime(
            manifest,
            manifest_path,
            run_root,
        )

        captured[
            "runtime"
        ] = runtime

        return runtime

    backend = LocalBackend(
        working_directory=tmp_path,
        runtime_factory=factory,
    )

    prepared = backend.prepare_plan(
        plan,
        execution_context=(
            execution_context
        ),
    )

    runtime = captured[
        "runtime"
    ]

    assert runtime.built is True
    assert runtime.environment is not None

    assert (
        runtime.environment[
            "BASE_VALUE"
        ]
        == "from-parent"
    )

    assert (
        runtime.environment[
            "SOURCE_ONLY"
        ]
        == "from-source"
    )

    # Explicit resolved variables win after sourcing.
    assert (
        runtime.environment[
            "PROFILE_VALUE"
        ]
        == "explicit"
    )

    assert (
        runtime.environment[
            "SECRET_TOKEN"
        ]
        == secret
    )

    # Materialization never changes the parent process environment.
    assert (
        os.environ.get(
            "PROFILE_VALUE"
        )
        is None
    )

    assert (
        os.environ.get(
            "SOURCE_ONLY"
        )
        is None
    )

    assert (
        os.environ.get(
            "SECRET_TOKEN"
        )
        is None
    )

    # Raw execution variables must not be serialized into the generated
    # compatibility manifest or PreparedExecution metadata.
    generated = (
        runtime.manifest_path
        .read_text(
            encoding="utf-8"
        )
    )

    assert secret not in generated
    assert (
        "SECRET_TOKEN"
        not in generated
    )

    assert secret not in repr(
        prepared.metadata
    )


def test_local_backend_does_not_require_environment_capability_without_env_semantics(
    tmp_path: Path,
) -> None:
    execution_context = (
        SystemExecutionContext(
            runtime={
                "mode": "realtime",
            },
        )
    )

    plan = plan_system(
        _system(),
        execution_context=(
            execution_context
        ),
    )

    captured: dict[
        str,
        LegacyRuntime,
    ] = {}

    def factory(
        manifest,
        manifest_path,
        run_root,
    ):
        runtime = LegacyRuntime(
            manifest,
            manifest_path,
            run_root,
        )

        captured[
            "runtime"
        ] = runtime

        return runtime

    backend = LocalBackend(
        working_directory=tmp_path,
        runtime_factory=factory,
    )

    backend.prepare_plan(
        plan,
        execution_context=(
            execution_context
        ),
    )

    assert (
        captured[
            "runtime"
        ].built
        is True
    )


def test_local_backend_refuses_to_ignore_required_execution_environment(
    tmp_path: Path,
) -> None:
    execution_context = (
        SystemExecutionContext(
            variables={
                "REQUIRED_VALUE": (
                    "exact"
                ),
            },
        )
    )

    plan = plan_system(
        _system(),
        execution_context=(
            execution_context
        ),
    )

    backend = LocalBackend(
        working_directory=tmp_path,
        runtime_factory=LegacyRuntime,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "does not support the explicit "
            "System execution environment"
        ),
    ):
        backend.prepare_plan(
            plan,
            execution_context=(
                execution_context
            ),
        )


def test_local_backend_reports_missing_execution_source(
    tmp_path: Path,
) -> None:
    missing = (
        tmp_path
        / "missing-setup.bash"
    )

    execution_context = (
        SystemExecutionContext(
            sources=(
                str(missing),
            ),
        )
    )

    plan = plan_system(
        _system(),
        execution_context=(
            execution_context
        ),
    )

    backend = LocalBackend(
        working_directory=tmp_path,
        runtime_factory=CaptureRuntime,
    )

    with pytest.raises(
        FileNotFoundError,
        match=(
            "Environment source files "
            "not found"
        ),
    ):
        backend.prepare_plan(
            plan,
            execution_context=(
                execution_context
            ),
        )
