from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def run_root(project: str | Path = ".") -> Path:
    return Path(project).expanduser().resolve() / ".nodrix" / "runs"


def list_runs(project: str | Path = ".") -> list[dict[str, Any]]:
    root = run_root(project)
    result: list[dict[str, Any]] = []
    if not root.is_dir():
        return result
    for directory in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        report_path = directory / "summary.json"
        if not report_path.is_file():
            report_path = directory / "run.json"
        report: dict[str, Any] = {}
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                report = {}
        result.append({
            "id": directory.name,
            "path": str(directory),
            "pipeline": report.get("pipeline"),
            "status": report.get("status", "unknown"),
            "duration_seconds": report.get("duration_seconds"),
        })
    return result


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
    for name in ("summary.json", "run.json"):
        path = directory / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"Run report not found in {directory}")


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
    return {
        "first": a.get("run_dir", first),
        "second": b.get("run_dir", second),
        "duration_seconds_delta": float(b.get("duration_seconds", 0.0)) - float(a.get("duration_seconds", 0.0)),
        "nodes": nodes,
    }
