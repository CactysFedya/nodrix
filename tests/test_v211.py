from __future__ import annotations

import asyncio
import json
from pathlib import Path
import threading

from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.runs import latest_run_id, list_runs, load_run


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_live_run_is_selected_over_completed_run(tmp_path: Path) -> None:
    root = tmp_path / ".nodrix" / "runs"
    completed = root / "completed"
    active = root / "active"

    _write_json(completed / "summary.json", {"status": "completed"})
    _write_json(active / "status.json", {"status": "running"})

    assert latest_run_id(tmp_path) == active.name


def test_final_summary_overrides_stale_status(tmp_path: Path) -> None:
    run = tmp_path / ".nodrix" / "runs" / "done"
    _write_json(run / "status.json", {"status": "running"})
    _write_json(run / "summary.json", {"status": "completed"})

    [item] = list_runs(tmp_path)

    assert item["status"] == "completed"
    assert load_run(run.name, tmp_path)["status"] == "completed"


def test_async_cancellation_requests_graceful_stop() -> None:
    async def scenario() -> None:
        runtime = object.__new__(HybridPipelineRuntime)
        runtime._start = threading.Event()
        runtime._stop = threading.Event()
        runtime._interrupted = threading.Event()
        runtime.edges = []

        def fake_run_sync() -> dict[str, object]:
            assert runtime._stop.wait(timeout=2.0)
            return {"status": "stopped"}

        runtime.run_sync = fake_run_sync

        task = asyncio.create_task(runtime.run())
        await asyncio.sleep(0.05)
        task.cancel()
        report = await task

        assert report["status"] == "stopped"
        assert runtime._interrupted.is_set()
        assert runtime._stop.is_set()

    asyncio.run(scenario())
