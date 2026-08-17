from __future__ import annotations

from pathlib import Path

import pytest

from nodrix.errors import RuntimeGraphError
from nodrix.hybrid_runtime import (
    HybridPipelineRuntime,
)
from nodrix.integration import (
    ApplicationContext,
    ResourceContext,
)
from nodrix.manifest import PipelineManifest
from nodrix.node import NodeContext
import nodrix.process_host as process_host
from nodrix.runtime_components import (
    LoadedApplication,
    LoadedResource,
    LoadedSession,
)


def _manifest(
    tmp_path: Path,
    *,
    integrations: bool = False,
) -> tuple[PipelineManifest, Path]:
    raw: dict = {
        "metadata": {
            "name": "runtime-environment",
        },
        "runtime": {
            "engine": "unified",
        },
        "nodes": {},
        "edges": [],
        "applications": {
            "application": {
                "uses": "test.missing_application",
                "parameters": {},
            },
        },
    }

    if integrations:
        raw["resources"] = {
            "resource": {
                "uses": "test.missing_resource",
                "parameters": {},
            },
        }

    manifest = PipelineManifest.model_validate(
        raw
    )

    path = tmp_path / "manifest.yaml"
    path.write_text(
        "metadata: {name: runtime-environment}\n"
        "nodes: {}\n"
        "edges: []\n",
        encoding="utf-8",
    )

    return manifest, path


def _runtime(
    tmp_path: Path,
    *,
    integrations: bool = False,
) -> HybridPipelineRuntime:
    manifest, path = _manifest(
        tmp_path,
        integrations=integrations,
    )

    return HybridPipelineRuntime(
        manifest,
        path,
        run_root=tmp_path / "runs",
    )


def test_explicit_runtime_environment_is_immutable(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path
    )

    supplied = {
        "EXACT_VALUE": "field",
    }

    runtime.set_execution_environment(
        supplied
    )

    supplied[
        "EXACT_VALUE"
    ] = "mutated"

    assert (
        runtime.environment_value(
            "EXACT_VALUE"
        )
        == "field"
    )

    snapshot = (
        runtime.execution_environment
    )

    with pytest.raises(
        TypeError,
    ):
        snapshot[
            "EXACT_VALUE"
        ] = "forbidden"  # type: ignore[index]


def test_runtime_environment_locks_at_build_boundary(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path
    )

    runtime.set_execution_environment(
        {
            "BOUND": "yes",
        }
    )

    with pytest.raises(
        RuntimeGraphError,
        match="Unknown provider application",
    ):
        runtime.build()

    with pytest.raises(
        RuntimeError,
        match="already locked",
    ):
        runtime.set_execution_environment(
            {
                "BOUND": "different",
            }
        )


def test_legacy_environment_is_frozen_when_build_starts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "NODRIX_RUNTIME_ENV_TEST",
        "before-build",
    )

    runtime = _runtime(
        tmp_path
    )

    monkeypatch.setenv(
        "NODRIX_RUNTIME_ENV_TEST",
        "at-build",
    )

    with pytest.raises(
        RuntimeGraphError,
        match="Unknown provider application",
    ):
        runtime.build()

    monkeypatch.setenv(
        "NODRIX_RUNTIME_ENV_TEST",
        "after-build",
    )

    assert (
        runtime.environment_value(
            "NODRIX_RUNTIME_ENV_TEST"
        )
        == "at-build"
    )


def test_context_environment_is_hidden_from_repr(
    tmp_path: Path,
) -> None:
    secret = {
        "API_TOKEN": "secret-value",
    }

    node = NodeContext(
        name="node",
        run_dir=tmp_path,
        project_dir=tmp_path,
        runtime_mode="default",
        environment=secret,
    )

    resource = ResourceContext(
        name="resource",
        run_dir=tmp_path,
        project_dir=tmp_path,
        runtime_mode="default",
        environment=secret,
    )

    application = ApplicationContext(
        name="application",
        run_dir=tmp_path,
        project_dir=tmp_path,
        runtime_mode="default",
        environment=secret,
    )

    assert "secret-value" not in repr(
        node
    )
    assert "secret-value" not in repr(
        resource
    )
    assert "secret-value" not in repr(
        application
    )


class _SessionProbe:
    def __init__(self) -> None:
        self.context = None

    def open(self, context) -> None:
        self.context = context

    def close(self) -> None:
        return None


class _ResourceProbe:
    def __init__(self) -> None:
        self.context = None

    def open(self, context) -> None:
        self.context = context

    def close(self) -> None:
        return None


class _ApplicationProbe:
    def __init__(self) -> None:
        self.context = None

    def configure(
        self,
        context,
    ) -> None:
        self.context = context

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


def test_integration_contexts_receive_runtime_snapshot(
    tmp_path: Path,
) -> None:
    runtime = _runtime(
        tmp_path,
        integrations=True,
    )

    runtime.set_execution_environment(
        {
            "ROBOT_MODEL": "rpi5",
            "FASTLIO_CONFIG_FILE": (
                "mid360s_handheld.yaml"
            ),
        }
    )

    manifest = runtime.manifest

    session = _SessionProbe()
    resource = _ResourceProbe()
    application = _ApplicationProbe()

    runtime.sessions = {
        "session": LoadedSession(
            name="session",
            uses="demo.session",
            instance=session,
        ),
    }

    runtime.resources = {
        "resource": LoadedResource(
            name="resource",
            uses="demo.resource",
            instance=resource,
            config=manifest.resources[
                "resource"
            ],
        ),
    }

    runtime.applications = {
        "application": LoadedApplication(
            name="application",
            uses="demo.application",
            instance=application,
            config=manifest.applications[
                "application"
            ],
        ),
    }

    run_dir = tmp_path / "run"

    runtime._open_sessions(
        run_dir
    )
    runtime._open_resources(
        run_dir
    )
    runtime._start_applications(
        run_dir
    )

    expected = (
        runtime.execution_environment
    )

    assert (
        session.context.environment
        is expected
    )

    assert (
        resource.context.environment
        is expected
    )

    assert (
        application.context.environment
        is expected
    )

    assert (
        application.context.environment[
            "FASTLIO_CONFIG_FILE"
        ]
        == "mid360s_handheld.yaml"
    )

    runtime._stop_applications()
    runtime._close_resources()
    runtime._close_sessions()


def test_child_environment_installation_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_environment = {
        "PARENT_ONLY": "parent",
    }

    monkeypatch.setattr(
        process_host.os,
        "environ",
        fake_environment,
    )

    process_host._install_child_environment(
        {
            "CHILD_ONLY": "child",
            "ROS_DOMAIN_ID": "42",
        }
    )

    assert fake_environment == {
        "CHILD_ONLY": "child",
        "ROS_DOMAIN_ID": "42",
    }


def test_child_environment_none_preserves_legacy_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_environment = {
        "PARENT_ONLY": "parent",
    }

    monkeypatch.setattr(
        process_host.os,
        "environ",
        fake_environment,
    )

    process_host._install_child_environment(
        None
    )

    assert fake_environment == {
        "PARENT_ONLY": "parent",
    }


def test_context_environment_default_is_legacy_neutral(
    tmp_path: Path,
) -> None:
    context = NodeContext(
        name="node",
        run_dir=tmp_path,
        project_dir=tmp_path,
        runtime_mode="default",
    )

    assert context.environment is None
