from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from rich.console import Console

from nodrix.presentation import (
    format_duration,
    render_health,
    render_run_active_info,
    render_run_summary,
    render_status,
    render_system_execution_status,
    render_system_plan,
    render_top_view,
)
from nodrix.workspace import create_workspace, default_view, set_active_context
from nodrix.ux import render_runtime_event
from nodrix.system import (
    ApplicationInstance,
    Artifact,
    Graph,
    NodeInstance,
    ResourceInstance,
    SystemLink,
    SystemModel,
    Target,
    plan_system,
)


def _plain(renderable) -> str:
    stream = StringIO()
    console = Console(
        file=stream,
        force_terminal=False,
        color_system=None,
        width=140,
    )
    console.print(renderable)
    return stream.getvalue()


def _runtime_snapshot() -> dict[str, object]:
    shared = {
        "scope": "executor_shared",
        "executor_cpu_percent": 82.5,
        "executor_rss_bytes": 420 * 1024 * 1024,
        # This value belongs to the executor scope and must not be presented as
        # an independently measured per-node CPU number.
        "cpu_percent": 82.5,
    }
    return {
        "pipeline": "semantic-mapping",
        "status": "running",
        "duration_seconds": 92.0,
        "system": {
            "cpu_count": 4,
            "memory_total_bytes": 8 * 1024 * 1024 * 1024,
            "temperature_c": 64.0,
            "load_average": [1.2, 1.0, 0.8],
        },
        "nodes": {
            "source": {
                "rate_hz": 30.0,
                "p95_ms": 1.2,
                "resources": shared,
                "health": {"status": "healthy", "ready": True, "alive": True},
            },
            "detector": {
                "rate_hz": 10.0,
                "p95_ms": 42.0,
                "resources": shared,
                "runtime_info": {"backend": "ncnn", "hardware": False, "threads": 4},
                "health": {"status": "healthy", "ready": True, "alive": True},
            },
        },
        "applications": {
            "camera": {
                "running": True,
                "status": "running",
                "pid": 1234,
                "restart_count": 0,
                "resources": {
                    "cpu_percent": 12.0,
                    "rss_bytes": 80 * 1024 * 1024,
                    "process_count": 1,
                    "thread_count": 6,
                },
            }
        },
        "edges": [
            {
                "source": "source.output",
                "target": "detector.input",
                "policy": "latest",
                "capacity": 1,
                "depth": 0,
                "stale_skips": 3,
                "overflow_drops": 0,
            }
        ],
    }


def test_top_views_are_borderless_and_compact_is_compatible_alias() -> None:
    data = _runtime_snapshot()
    for view in ("compact", "overview", "performance", "operations", "debug"):
        output = _plain(render_top_view(data, view))
        assert "NODRIX" in output
        assert "semantic-mapping" in output
        assert not any(char in output for char in "┏┓┗┛┃╭╮╰╯")


def test_performance_view_labels_shared_executor_resources_honestly() -> None:
    output = _plain(render_top_view(_runtime_snapshot(), "performance"))
    assert "shared executor" in output
    assert "BOTTLENECK" not in output
    assert "stale=3" in output


def test_status_is_summary_first_instead_of_dumping_a_table() -> None:
    output = _plain(render_status(_runtime_snapshot(), run_id="run-1"))
    assert "2 healthy" in output
    assert "no queue overflow" in output
    assert "Run" in output
    assert "run-1" in output
    assert "Node State Health CPU" not in output


def test_system_plan_is_rendered_as_architecture_sections() -> None:
    plan = plan_system(
        SystemModel(
            name="robot",
            targets=(
                Target(name="pi", kind="host", properties={"backend": "local"}),
                Target(name="worker", kind="host", properties={"backend": "remote"}),
            ),
            resources=(
                ResourceInstance(name="camera", uses="demo.camera", target="pi"),
            ),
            applications=(
                ApplicationInstance(name="driver", uses="demo.driver", target="pi"),
            ),
            graphs=(
                Graph(
                    name="capture",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="demo.source",
                            target="pi",
                            resources={"camera": "camera"},
                        ),
                    ),
                ),
                Graph(
                    name="mapping",
                    nodes=(NodeInstance(name="sink", uses="demo.sink", target="worker"),),
                ),
            ),
            links=(
                SystemLink(
                    **{
                        "from": "capture/source.output",
                        "to": "mapping/sink.input",
                        "uses": "demo.transport",
                    }
                ),
            ),
            artifacts=(
                Artifact(
                    name="map",
                    kind="map",
                    producer="mapping/sink.output",
                    path="maps/map.bin",
                ),
            ),
        )
    )
    output = _plain(render_system_plan(plan))
    assert "PLAN robot" in output
    assert "BACKENDS" in output
    assert "GRAPH CAPTURE" in output
    assert "GRAPH MAPPING" in output
    assert "cross_target" in output
    assert "demo.transport" in output
    assert "map" in output
    assert not any(char in output for char in "┏┓┗┛┃╭╮╰╯")


def test_default_top_view_follows_active_workspace_context(tmp_path) -> None:
    root = tmp_path / "project"
    create_workspace(root)
    project_file = root / "nodrix.yaml"
    import yaml

    config = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    config["contexts"]["perf"] = {
        "environment": "local",
        "profile": "default",
        "view": "performance",
    }
    project_file.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    set_active_context(root, "perf")

    assert default_view(root) == "performance"


def test_workspace_view_yaml_controls_top_sections(tmp_path) -> None:
    from nodrix.workspace_views import render_top_view as render_workspace_top

    root = tmp_path / "project"
    (root / "views").mkdir(parents=True)
    (root / "views/minimal.yaml").write_text(
        """schema: nodrix.view/v1
name: minimal
style:
  borders: none
sections:
  - runtime
  - health
  - attention
""",
        encoding="utf-8",
    )
    output = _plain(render_workspace_top(_runtime_snapshot(), "minimal", project=root))
    assert "CPU" in output
    assert "ATTENTION" not in output
    assert "APPLICATIONS" not in output
    assert "GRAPH" not in output



def test_subsecond_duration_remains_visible() -> None:
    assert format_duration(0.048) == "48 ms"
    assert format_duration(0.0004) == "<1 ms"


def test_healthy_snapshot_has_no_false_attention_or_bottleneck() -> None:
    output = _plain(render_top_view(_runtime_snapshot(), "performance"))
    assert "BOTTLENECK" not in output
    assert "ATTENTION" not in output


def test_completed_health_hides_shutdown_alive_ready_flags() -> None:
    data = _runtime_snapshot()
    data["status"] = "completed"
    data["duration_seconds"] = 0.048
    for raw in data["nodes"].values():
        raw["health"]["state"] = "stopped"
        raw["health"]["alive"] = False
        raw["health"]["ready"] = False
    output = _plain(render_health(data))
    assert "48 ms" in output
    assert "STOPPED · healthy" in output
    assert "alive no" not in output
    assert "ready no" not in output
    assert "completed cleanly" in output


def test_operations_keeps_graph_and_hides_empty_sections() -> None:
    data = _runtime_snapshot()
    data["applications"] = {}
    output = _plain(render_top_view(data, "operations"))
    assert "GRAPH" in output
    assert "APPLICATIONS" not in output
    assert "MONITORS" not in output
    assert "ATTENTION" not in output


def test_run_summary_is_borderless_and_compact() -> None:
    report = _runtime_snapshot()
    report["status"] = "completed"
    report["duration_seconds"] = 0.048
    report["run_dir"] = "/tmp/project/.nodrix/runs/run-1"
    for raw in report["nodes"].values():
        raw["messages"] = 5
        raw["errors"] = 0
    output = _plain(render_run_summary(report))
    assert "COMPLETED" in output
    assert "48 ms" in output
    assert "5 messages · 0 errors · 0 drops" in output
    assert ".nodrix/runs/run-1" in output
    assert "/tmp/project" not in output
    assert "Node State Health CPU" not in output
    assert not any(char in output for char in "┏┓┗┛┃╭╮╰╯")



def test_runtime_ready_events_use_completion_summary() -> None:
    indexes = {"source": 1, "writer": 4}
    ready = _plain(
        render_runtime_event(
            {
                "kind": "node_ready",
                "node": "writer",
                "uses": "sink.jsonl",
            },
            indexes,
            4,
        )
    )
    assert "writer" in ready
    assert "ready" in ready
    assert "4/4" not in ready
    assert "1/4" not in ready

    running = _plain(
        render_runtime_event(
            {"kind": "pipeline_running"},
            indexes,
            4,
        )
    )
    assert "4/4 ready" in running
    assert "RUNNING" in running


def test_run_active_info_uses_short_workspace_artifact_path() -> None:
    output = _plain(
        render_run_active_info(
            "/Users/demo/project/.nodrix/runs",
            monitor_command="plyctl top",
        )
    )
    assert "Artifacts" in output
    assert ".nodrix/runs" in output
    assert "/Users/demo/project" not in output
    assert "Monitor" in output
    assert "plyctl top" in output


def _execution_state(
    value: str,
):
    return SimpleNamespace(
        value=value,
    )


def _scope_status(
    scope: str,
    state: str,
    *,
    execution_id: str = "local-001",
    message: str | None = None,
):
    target, backend = scope.split(
        ":",
        1,
    )

    return SimpleNamespace(
        scope=SimpleNamespace(
            id=scope,
            target=target,
            backend=backend,
        ),
        status=SimpleNamespace(
            state=_execution_state(
                state
            ),
            backend=backend,
            execution_id=execution_id,
            message=message,
        ),
    )


def _system_status(
    state: str,
    *,
    execution_id: str,
    scopes=(),
    systems=(),
    message: str | None = None,
):
    return SimpleNamespace(
        state=_execution_state(
            state
        ),
        execution_id=execution_id,
        scopes=tuple(scopes),
        systems=tuple(systems),
        message=message,
    )


def _child_system_status(
    role: str,
    definition: str,
    status,
):
    return SimpleNamespace(
        name=role,
        instance=SimpleNamespace(
            plan=SimpleNamespace(
                system=definition,
            )
        ),
        status=status,
    )


def test_system_execution_status_renders_flat_scope() -> None:
    status = _system_status(
        "running",
        execution_id="system-root",
        scopes=(
            _scope_status(
                "pi5:local",
                "running",
            ),
        ),
    )

    output = _plain(
        render_system_execution_status(
            "livox-mid360",
            status,
        )
    )

    assert "● livox-mid360" in output
    assert "RUNNING" in output
    assert "pi5:local" in output
    assert "local:local-001" in output
    assert "scopes=1" in output
    assert "systems=0" in output


def test_system_execution_status_renders_child_system_identity() -> None:
    child = _system_status(
        "running",
        execution_id="system-child",
        scopes=(
            _scope_status(
                "pi5:local",
                "running",
            ),
        ),
    )
    root = _system_status(
        "running",
        execution_id="system-root",
        systems=(
            _child_system_status(
                "lidar",
                "livox-mid360",
                child,
            ),
        ),
    )

    output = _plain(
        render_system_execution_status(
            "rpi5-mapping",
            root,
        )
    )

    assert "rpi5-mapping" in output
    assert "lidar → livox-mid360" in output
    assert "pi5:local" in output
    assert "systems=1" in output


def test_system_execution_status_renders_deep_hierarchy() -> None:
    driver = _system_status(
        "running",
        execution_id="system-driver",
        scopes=(
            _scope_status(
                "pi5:local",
                "running",
            ),
        ),
    )
    lidar = _system_status(
        "running",
        execution_id="system-lidar",
        systems=(
            _child_system_status(
                "driver",
                "livox-driver",
                driver,
            ),
        ),
    )
    robot = _system_status(
        "running",
        execution_id="system-robot",
        systems=(
            _child_system_status(
                "lidar",
                "livox-mid360",
                lidar,
            ),
        ),
    )

    output = _plain(
        render_system_execution_status(
            "robot",
            robot,
        )
    )

    assert "lidar → livox-mid360" in output
    assert "driver → livox-driver" in output
    assert "pi5:local" in output


def test_system_execution_status_renders_leaf_failure_reason_once() -> None:
    failed_scope = _scope_status(
        "pi5:local",
        "failed",
        message=(
            "RuntimeError: process exited "
            "with code 1"
        ),
    )

    child = _system_status(
        "failed",
        execution_id="system-child",
        scopes=(
            failed_scope,
        ),
        message=(
            "RuntimeError: process exited "
            "with code 1"
        ),
    )

    root = _system_status(
        "failed",
        execution_id="system-root",
        systems=(
            _child_system_status(
                "localization",
                "fast-livo2",
                child,
            ),
        ),
        message=(
            "RuntimeError: process exited "
            "with code 1"
        ),
    )

    output = _plain(
        render_system_execution_status(
            "rpi5-mapping",
            root,
        )
    )

    assert "✗ rpi5-mapping" in output
    assert (
        "localization → fast-livo2"
        in output
    )
    assert "pi5:local" in output
    assert "FAILED" in output
    assert (
        output.count(
            "RuntimeError: process exited "
            "with code 1"
        )
        == 1
    )
