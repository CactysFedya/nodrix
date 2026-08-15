from __future__ import annotations

import threading
import time
from pathlib import Path

from nodrix.system import (
    ApplicationInstance,
    BackendExecutionState,
    Graph,
    LocalBackend,
    NodeInstance,
    ResourceInstance,
    SystemLink,
    SystemModel,
    Target,
    lower_local_context,
    plan_system,
)


class FakeRuntime:
    def __init__(self, manifest, manifest_path, run_root):
        self.manifest = manifest
        self.manifest_path = manifest_path
        self.run_root = run_root
        self.stop_event = threading.Event()
        self.built = False

    def build(self):
        self.built = True

    def run_sync(self):
        self.stop_event.wait(0.05)
        return {
            "pipeline": self.manifest.metadata.name,
            "status": "stopped" if self.stop_event.is_set() else "completed",
        }

    def request_stop(self):
        self.stop_event.set()


def _simple_plan():
    return plan_system(
        SystemModel(
            name="local-system",
            targets=(Target(name="local", kind="local"),),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(name="source", uses="demo.source"),
                        NodeInstance(name="sink", uses="demo.sink"),
                    ),
                    connections=(
                        {"from": "source.output", "to": "sink.input"},
                    ),
                ),
            ),
        )
    )


def test_lowering_creates_legacy_pipeline_manifest() -> None:
    context = LocalBackend(
        runtime_factory=FakeRuntime,
    ).context(_simple_plan())

    lowered = lower_local_context(context)

    assert lowered.manifest.metadata.name == "local-system"
    assert lowered.manifest.runtime.engine == "unified"
    assert set(lowered.manifest.nodes) == {"source", "sink"}
    assert lowered.manifest.edges[0].source == "source.output"
    assert lowered.manifest.edges[0].target == "sink.input"


def test_lowering_namespaces_duplicate_node_names_across_graphs() -> None:
    plan = plan_system(
        SystemModel(
            name="duplicates",
            graphs=(
                Graph(
                    name="camera",
                    nodes=(NodeInstance(name="worker", uses="demo.a"),),
                ),
                Graph(
                    name="mapping",
                    nodes=(NodeInstance(name="worker", uses="demo.b"),),
                ),
            ),
            links=(
                SystemLink(
                    **{
                        "from": "camera/worker.output",
                        "to": "mapping/worker.input",
                    }
                ),
            ),
        )
    )
    context = LocalBackend(runtime_factory=FakeRuntime).context(plan)

    lowered = lower_local_context(context)

    assert set(lowered.manifest.nodes) == {
        "camera__worker",
        "mapping__worker",
    }
    assert lowered.manifest.edges[0].source == "camera__worker.output"
    assert lowered.manifest.edges[0].target == "mapping__worker.input"


def test_application_boundary_lowers_to_external_link() -> None:
    plan = plan_system(
        SystemModel(
            name="application-link",
            applications=(
                ApplicationInstance(name="driver", uses="demo.driver"),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(NodeInstance(name="source", uses="demo.source"),),
                ),
            ),
            links=(
                SystemLink(
                    **{
                        "from": "driver.output",
                        "to": "main/source.external",
                        "uses": "demo.transport",
                    }
                ),
            ),
        )
    )
    context = LocalBackend(runtime_factory=FakeRuntime).context(plan)
    lowered = lower_local_context(context)

    assert len(lowered.manifest.links) == 1
    assert lowered.manifest.links[0].source == "driver.output"
    assert lowered.manifest.links[0].target == "source.external"
    assert lowered.manifest.links[0].uses == "demo.transport"


def test_local_backend_rejects_cross_backend_links() -> None:
    plan = plan_system(
        SystemModel(
            name="multi",
            targets=(
                Target(
                    name="local",
                    kind="local",
                    properties={"backend": "local"},
                ),
                Target(
                    name="remote",
                    kind="host",
                    properties={"backend": "remote"},
                ),
            ),
            graphs=(
                Graph(
                    name="left",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="demo.source",
                            target="local",
                        ),
                    ),
                ),
                Graph(
                    name="right",
                    nodes=(
                        NodeInstance(
                            name="sink",
                            uses="demo.sink",
                            target="remote",
                        ),
                    ),
                ),
            ),
            links=(
                SystemLink(
                    **{
                        "from": "left/source.output",
                        "to": "right/sink.input",
                        "uses": "demo.transport",
                    }
                ),
            ),
        )
    )
    backend = LocalBackend(runtime_factory=FakeRuntime)
    report = backend.validate_plan(plan)

    assert not report.valid
    assert any(item.code == "LOCAL101" for item in report.errors)


def test_new_resource_to_resource_dependency_is_rejected() -> None:
    plan = plan_system(
        SystemModel(
            name="resources",
            resources=(
                ResourceInstance(name="base", uses="demo.base"),
                ResourceInstance(
                    name="child",
                    uses="demo.child",
                    bindings={"base": "base"},
                ),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(NodeInstance(name="source", uses="demo.source"),),
                ),
            ),
        )
    )
    backend = LocalBackend(runtime_factory=FakeRuntime)
    report = backend.validate_plan(plan)

    assert not report.valid
    assert any(item.code == "LOCAL102" for item in report.errors)


def test_local_backend_prepare_builds_existing_runtime(tmp_path: Path) -> None:
    backend = LocalBackend(
        working_directory=tmp_path,
        runtime_factory=FakeRuntime,
    )

    prepared = backend.prepare_plan(_simple_plan())

    assert prepared.backend == "local"
    assert prepared.payload.runtime.built is True
    assert prepared.payload.manifest_path.is_file()
    assert prepared.metadata["legacy_snapshot"] is False


def test_local_backend_start_is_non_blocking_and_completes(tmp_path: Path) -> None:
    backend = LocalBackend(
        working_directory=tmp_path,
        runtime_factory=FakeRuntime,
    )
    prepared = backend.prepare_plan(_simple_plan())

    started = time.perf_counter()
    handle = backend.start(prepared)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5

    deadline = time.monotonic() + 2
    status = backend.inspect(handle)
    while not status.terminal and time.monotonic() < deadline:
        time.sleep(0.01)
        status = backend.inspect(handle)

    assert status.state is BackendExecutionState.COMPLETED
    assert status.details["report"]["pipeline"] == "local-system"


def test_local_backend_stop_delegates_to_runtime(tmp_path: Path) -> None:
    class BlockingRuntime(FakeRuntime):
        def run_sync(self):
            self.stop_event.wait(5)
            return {
                "pipeline": self.manifest.metadata.name,
                "status": "stopped",
            }

    backend = LocalBackend(
        working_directory=tmp_path,
        runtime_factory=BlockingRuntime,
        stop_timeout_seconds=1,
    )
    prepared = backend.prepare_plan(_simple_plan())
    handle = backend.start(prepared)

    status = backend.stop(handle, timeout_seconds=1)

    assert status.state is BackendExecutionState.STOPPED
    assert status.terminal


def test_local_backend_is_public_through_plyctl() -> None:
    from plyctl import LocalBackend as PublicLocalBackend

    assert PublicLocalBackend is LocalBackend
