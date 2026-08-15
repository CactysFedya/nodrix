from __future__ import annotations

from pathlib import Path

from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.manifest import PipelineManifest
from nodrix.system import Graph, LocalBackend, NodeInstance, SystemModel, plan_system


def _manifest() -> PipelineManifest:
    return PipelineManifest.model_validate(
        {
            "metadata": {"name": "system-runtime-root"},
            "runtime": {"engine": "unified"},
            "nodes": {
                "worker": {
                    "uses": "demo.worker",
                }
            },
            "edges": [],
        }
    )


def test_hybrid_runtime_can_keep_generated_manifest_outside_project_root(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    generated = project / ".nodrix" / "system-generated" / "generated.yaml"
    generated.parent.mkdir(parents=True)

    runtime = HybridPipelineRuntime(
        _manifest(),
        generated,
        base_dir=project,
    )

    assert runtime.manifest_path == generated.resolve()
    assert runtime.base_dir == project.resolve()
    assert runtime.run_root == (project / ".nodrix" / "runs").resolve()


def test_hybrid_runtime_legacy_default_still_uses_manifest_parent(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "pipeline.yaml"

    runtime = HybridPipelineRuntime(_manifest(), manifest_path)

    assert runtime.base_dir == tmp_path.resolve()
    assert runtime.run_root == (tmp_path / ".nodrix" / "runs").resolve()


def test_local_backend_passes_real_project_root_to_default_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "robot"
    project.mkdir()
    captured = {}

    class FakeRuntime:
        def build(self) -> None:
            pass

    def fake_default_factory(
        manifest,
        manifest_path,
        run_root,
        *,
        base_dir=None,
    ):
        captured["manifest_path"] = Path(manifest_path)
        captured["run_root"] = run_root
        captured["base_dir"] = Path(base_dir)
        return FakeRuntime()

    import nodrix.system.local_backend as module

    monkeypatch.setattr(module, "_default_runtime_factory", fake_default_factory)

    plan = plan_system(
        SystemModel(
            name="project-root",
            graphs=(
                Graph(
                    name="main",
                    nodes=(NodeInstance(name="worker", uses="demo.worker"),),
                ),
            ),
        )
    )

    backend = LocalBackend(working_directory=project)
    prepared = backend.prepare_plan(plan)

    assert captured["base_dir"] == project.resolve()
    assert ".nodrix/system-generated" in captured["manifest_path"].as_posix()
    assert prepared.payload.manifest_path == captured["manifest_path"]


def test_custom_runtime_factory_keeps_three_argument_contract(
    tmp_path: Path,
) -> None:
    project = tmp_path / "robot"
    project.mkdir()
    captured = {}

    class FakeRuntime:
        def build(self) -> None:
            pass

    def factory(manifest, manifest_path, run_root):
        captured["args"] = (manifest, Path(manifest_path), run_root)
        return FakeRuntime()

    plan = plan_system(
        SystemModel(
            name="custom-factory",
            graphs=(
                Graph(
                    name="main",
                    nodes=(NodeInstance(name="worker", uses="demo.worker"),),
                ),
            ),
        )
    )

    backend = LocalBackend(
        working_directory=project,
        runtime_factory=factory,
    )
    backend.prepare_plan(plan)

    assert len(captured["args"]) == 3
