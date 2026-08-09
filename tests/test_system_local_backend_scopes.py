from __future__ import annotations

from pathlib import Path

from nodrix.system import LocalBackend

from .test_system_local_backend import FakeRuntime, _simple_plan


def test_local_backend_scope_names_isolate_generated_manifests(tmp_path: Path) -> None:
    robot = LocalBackend(
        working_directory=tmp_path,
        runtime_factory=FakeRuntime,
        scope_name="robot",
    ).prepare_plan(_simple_plan())
    workstation = LocalBackend(
        working_directory=tmp_path,
        runtime_factory=FakeRuntime,
        scope_name="workstation",
    ).prepare_plan(_simple_plan())

    assert robot.payload.manifest_path.is_file()
    assert workstation.payload.manifest_path.is_file()
    assert robot.payload.manifest_path != workstation.payload.manifest_path
    assert robot.payload.manifest_path.name.endswith("-robot-local.yaml")
    assert workstation.payload.manifest_path.name.endswith(
        "-workstation-local.yaml"
    )


def test_local_backend_without_scope_keeps_legacy_manifest_name(tmp_path: Path) -> None:
    prepared = LocalBackend(
        working_directory=tmp_path,
        runtime_factory=FakeRuntime,
    ).prepare_plan(_simple_plan())

    assert prepared.payload.manifest_path.name.endswith("-local.yaml")
    assert "-local-local.yaml" not in prepared.payload.manifest_path.name
