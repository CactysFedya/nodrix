from __future__ import annotations

from rich.console import Console

from nodrix.system import (
    BackendExecutionState,
    BackendExecutionStatus,
    Graph,
    NodeInstance,
    SystemModel,
    plan_system,
)
from nodrix.system_presentation import (
    render_system_error,
    render_system_plan_result,
    render_system_run_intro,
    render_system_terminal,
)


def _plain(renderable) -> str:
    console = Console(record=True, width=140, color_system=None)
    console.print(renderable)
    return console.export_text()


def _plan(*, uses: str = "demo.worker"):
    return plan_system(
        SystemModel(
            name="demo",
            graphs=(
                Graph(
                    name="main",
                    nodes=(NodeInstance(name="worker", uses=uses),),
                ),
            ),
        )
    )


def test_system_plan_is_borderless_and_semantic() -> None:
    output = _plain(render_system_plan_result(_plan()))

    assert "NODRIX PLAN demo" in output
    assert "BACKENDS" in output
    assert "GRAPH MAIN" in output
    assert "worker" in output
    assert "plan ready" in output
    assert not any(char in output for char in "┏┓┗┛┃╭╮╰╯")


def test_system_run_intro_exposes_flow_before_execution() -> None:
    plan = _plan(uses="media.ffmpeg_source")
    output = _plain(
        render_system_run_intro(
            SystemModel(name="demo"),
            plan,
            "/tmp/project/systems/demo.yaml",
        )
    )

    assert "NODRIX RUN demo" in output
    assert "FLOW" in output
    assert "main" in output
    assert "worker" in output


def test_terminal_report_surfaces_reason_traffic_and_component_state() -> None:
    plan = _plan()
    status = BackendExecutionStatus(
        backend="local",
        execution_id="local-abc",
        state=BackendExecutionState.COMPLETED,
        details={
            "report": {
                "pipeline": "demo",
                "status": "completed",
                "duration_seconds": 1.25,
                "nodes": {
                    "worker": {
                        "messages": 20,
                        "errors": 0,
                        "rate_hz": 10.0,
                        "health": {"status": "healthy"},
                    }
                },
                "run_dir": "/tmp/project/.nodrix/runs/demo-1",
            }
        },
    )

    output = _plain(
        render_system_terminal(
            "demo",
            status,
            plan,
            elapsed_seconds=1.25,
        )
    )

    assert "COMPLETED" in output
    assert "Reason" in output
    assert "runtime returned normally" in output
    assert "20 messages" in output
    assert "COMPONENTS" in output
    assert "worker" in output
    assert "10.0 Hz" in output
    assert ".nodrix/runs/demo-1" in output


def test_continuous_fast_completion_is_called_out() -> None:
    plan = _plan(uses="media.ffmpeg_source")
    status = BackendExecutionStatus(
        backend="local",
        execution_id="local-abc",
        state=BackendExecutionState.COMPLETED,
    )

    output = _plain(
        render_system_terminal(
            "demo",
            status,
            plan,
            elapsed_seconds=0.2,
        )
    )

    assert "completed without a stop request" in output
    assert "Continuous sources normally remain RUNNING" in output


def test_system_error_has_stage_error_and_hint() -> None:
    output = _plain(
        render_system_error(
            "prepare",
            "model is missing",
            code="MODEL001",
            hint="Check the configured model path.",
        )
    )

    assert "PREPARE FAILED" in output
    assert "MODEL001" in output
    assert "model is missing" in output
    assert "Check the configured model path" in output
