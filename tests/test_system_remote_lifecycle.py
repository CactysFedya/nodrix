from __future__ import annotations

from pathlib import Path
import time

from nodrix.system import (
    BackendExecutionState,
    Graph,
    NodeInstance,
    RemoteAgentServer,
    RemoteProcessBackend,
    SystemModel,
    SystemOrchestrator,
    Target,
    plan_execution_scopes,
    plan_system,
)


TOKEN_ENV = "NODRIX_TEST_REMOTE_LIFECYCLE_TOKEN"


def _plan(
    *,
    host: str,
    port: int,
    uses: str,
    parameters: dict | None = None,
) -> object:
    return plan_system(
        SystemModel(
            name="remote-lifecycle",
            targets=(
                Target(
                    name="robot",
                    kind="host",
                    properties={
                        "backend": "process",
                        "agent": {
                            "host": host,
                            "port": port,
                            "token_env": TOKEN_ENV,
                        },
                    },
                ),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="worker",
                            uses=uses,
                            target="robot",
                            parameters=parameters or {},
                        ),
                    ),
                ),
            ),
        )
    )


def _orchestrator(plan, tmp_path: Path) -> SystemOrchestrator:
    scope = plan_execution_scopes(plan)[0]
    return SystemOrchestrator(
        {scope: RemoteProcessBackend(working_directory=tmp_path)}
    )


def test_remote_stop_propagates_to_process_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = "remote-stop-token"
    monkeypatch.setenv(TOKEN_ENV, token)

    with RemoteAgentServer(
        token=token,
        working_directory=tmp_path / "agent-work",
        run_root=tmp_path / "agent-runs",
    ) as server:
        host, port = server.address
        plan = _plan(
            host=host,
            port=port,
            uses="core.synthetic_source",
            parameters={
                "count": 100000,
                "interval_ms": 25,
            },
        )
        orchestrator = _orchestrator(plan, tmp_path)
        prepared = orchestrator.prepare_plan(plan)
        handle = orchestrator.start(prepared)

        time.sleep(0.1)
        status = orchestrator.stop(handle, timeout_seconds=2.0)

        assert status.state is BackendExecutionState.STOPPED, status
        assert status.scopes[0].status.details["remote"] is True
        assert status.scopes[0].status.details["alive"] is False


def test_remote_runtime_failure_propagates_after_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = "remote-failure-token"
    monkeypatch.setenv(TOKEN_ENV, token)
    module = tmp_path / "remote_failure_node.py"
    module.write_text(
        "from nodrix.node import SourceNode\n"
        "class RemoteFailureNode(SourceNode):\n"
        "    output_types = {'output': 'core.any'}\n"
        "    def produce(self):\n"
        "        raise RuntimeError('remote runtime exploded')\n"
        "        yield {'output': None}\n",
        encoding="utf-8",
    )

    with RemoteAgentServer(
        token=token,
        working_directory=tmp_path / "agent-work",
        run_root=tmp_path / "agent-runs",
    ) as server:
        host, port = server.address
        plan = _plan(
            host=host,
            port=port,
            uses=f"{module}:RemoteFailureNode",
        )
        orchestrator = _orchestrator(plan, tmp_path)
        prepared = orchestrator.prepare_plan(plan)
        handle = orchestrator.start(prepared)

        deadline = time.monotonic() + 10.0
        status = orchestrator.inspect(handle)
        while not status.terminal and time.monotonic() < deadline:
            time.sleep(0.05)
            status = orchestrator.inspect(handle)

        assert status.state is BackendExecutionState.FAILED, status
        assert "remote runtime exploded" in (
            status.scopes[0].status.message or ""
        )
        assert status.scopes[0].status.details["remote"] is True
