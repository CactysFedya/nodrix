from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .benchmarking import aggregate_reports


_ACTIVE_RUN_STATUSES = {
    "starting",
    "running",
    "rate_limited",
    "degraded",
    "stopping",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def run_root(project: str | Path = ".") -> Path:
    return Path(project).expanduser().resolve() / ".nodrix" / "runs"


def list_runs(project: str | Path = ".") -> list[dict[str, Any]]:
    root = run_root(project)
    result: list[dict[str, Any]] = []
    if not root.is_dir():
        return result

    for directory in (path for path in root.iterdir() if path.is_dir()):
        # Final reports are authoritative. status.json is used only while a
        # run has not produced summary.json or run.json yet.
        report: dict[str, Any] = {}
        report_path: Path | None = None
        for name in ("summary.json", "run.json", "status.json"):
            candidate = directory / name
            if candidate.is_file():
                loaded = _read_json(candidate)
                if loaded:
                    report = loaded
                    report_path = candidate
                    break

        updated_ns = (
            report_path.stat().st_mtime_ns
            if report_path is not None
            else directory.stat().st_mtime_ns
        )
        result.append(
            {
                "id": directory.name,
                "path": str(directory),
                "pipeline": report.get("pipeline"),
                "status": report.get("status", "starting"),
                "duration_seconds": report.get("duration_seconds"),
                "updated_ns": updated_ns,
            }
        )

    result.sort(
        key=lambda item: (int(item.get("updated_ns", 0)), str(item["id"])),
        reverse=True,
    )
    return result


def latest_run_id(project: str | Path = ".") -> str:
    items = list_runs(project)
    if not items:
        raise LookupError("No Plyctl runs found")

    active = [
        item
        for item in items
        if str(item.get("status", "")).lower() in _ACTIVE_RUN_STATUSES
    ]
    return str((active or items)[0]["id"])


def resolve_run(run_id: str, project: str | Path = ".") -> Path:
    root = run_root(project)
    exact = root / run_id
    if exact.is_dir():
        return exact
    matches = [path for path in root.glob(f"*{run_id}*") if path.is_dir()]
    if len(matches) != 1:
        raise LookupError(f"Run id {run_id!r} matched {len(matches)} runs")
    return matches[0]


def load_run(run_id: str, project: str | Path = ".") -> dict[str, Any]:
    directory = resolve_run(run_id, project)
    for name in ("summary.json", "run.json", "status.json"):
        path = directory / name
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return {
        "run_dir": str(directory),
        "id": directory.name,
        "status": "starting",
        "nodes": {},
        "edges": [],
        "streams": {},
    }


def _metric(first: float, second: float) -> dict[str, float | None]:
    delta = second - first
    percent = None if first == 0 else delta / abs(first) * 100.0
    return {"first": first, "second": second, "delta": delta, "percent": percent}


def _mean_metric(summary: Mapping[str, Any], name: str) -> float:
    value = dict(summary.get(name) or {}).get("mean", 0.0)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def compare_runs(first: str, second: str, project: str | Path = ".") -> dict[str, Any]:
    a = load_run(first, project)
    b = load_run(second, project)
    node_names = sorted(set(a.get("nodes", {})) | set(b.get("nodes", {})))
    nodes: dict[str, Any] = {}
    for name in node_names:
        left = dict(a.get("nodes", {}).get(name, {}))
        right = dict(b.get("nodes", {}).get(name, {}))
        nodes[name] = {
            "messages_delta": int(right.get("messages", 0)) - int(left.get("messages", 0)),
            "p95_ms_delta": float(right.get("p95_ms", 0.0)) - float(left.get("p95_ms", 0.0)),
            "errors_delta": int(right.get("errors", 0)) - int(left.get("errors", 0)),
        }

    left_summary = aggregate_reports([a])
    right_summary = aggregate_reports([b])
    metric_names = (
        "duration_seconds",
        "source_rate_hz",
        "sink_rate_hz",
        "end_to_end_p95_ms",
        "dropped_messages",
        "estimated_memory_bytes",
    )
    metrics = {
        name: _metric(_mean_metric(left_summary, name), _mean_metric(right_summary, name))
        for name in metric_names
    }
    return {
        "first": a.get("run_dir", first),
        "second": b.get("run_dir", second),
        "duration_seconds_delta": float(b.get("duration_seconds", 0.0)) - float(a.get("duration_seconds", 0.0)),
        "nodes": nodes,
        "metrics": metrics,
    }
