from __future__ import annotations

from pathlib import Path

from nodrix.system import Graph, LocalBackend, NodeInstance, SystemModel, plan_system


class FakeRuntime:
    def __init__(self, manifest, manifest_path, run_root):
        self.manifest = manifest
        self.manifest_path = manifest_path
        self.run_root = run_root
        self.built = False

    def build(self):
        self.built = True


def test_local_backend_project_activation_helper_is_lazy_and_callable(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    components = project / "components"
    components.mkdir(parents=True)

    (components / "nodes.py").write_text(
        "from plyctl import node\n\n"
        "@node\n"
        "def worker() -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )

    plan = plan_system(
        SystemModel(
            name="project-backed",
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="worker",
                            uses="local.worker",
                        ),
                    ),
                ),
            ),
        )
    )

    backend = LocalBackend(
        project=project,
        runtime_factory=FakeRuntime,
    )
    prepared = backend.prepare_plan(plan)

    assert prepared.payload.project is not None
    assert prepared.payload.runtime.built is True
    assert prepared.payload.manifest_path.is_file()
