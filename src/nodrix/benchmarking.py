from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
from typing import Any, Callable, Iterable, Mapping, Sequence

import yaml


BENCHMARK_SCHEMA = "nodrix.benchmark/v1"
RunCallable = Callable[[Path, Path, str | None, list[str], list[str]], Mapping[str, Any]]


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _summary(values: Iterable[float]) -> dict[str, float]:
    samples = [float(value) for value in values]
    if not samples:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0}
    return {
        "mean": statistics.fmean(samples),
        "min": min(samples),
        "max": max(samples),
        "p50": _percentile(samples, 0.50),
        "p95": _percentile(samples, 0.95),
        "p99": _percentile(samples, 0.99),
    }


def _safe_name(value: str) -> str:
    rendered = "".join(char if char.isalnum() or char in "-_" else "-" for char in value).strip("-")
    return rendered or "benchmark"


def _json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n"
    path.write_text(rendered, encoding="utf-8")


@dataclass(frozen=True, slots=True)
class BenchmarkVariant:
    name: str
    profile: str | None = None
    set_values: tuple[str, ...] = ()
    block_values: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, name: str, raw: Mapping[str, Any] | None) -> "BenchmarkVariant":
        data = dict(raw or {})
        unknown = sorted(set(data) - {"profile", "set", "block"})
        if unknown:
            raise ValueError(f"Variant {name!r} contains unsupported fields: {', '.join(unknown)}")
        set_values = data.get("set") or []
        block_values = data.get("block") or []
        if isinstance(set_values, str) or isinstance(block_values, str):
            raise ValueError(f"Variant {name!r} set/block values must be YAML lists")
        return cls(
            name=name,
            profile=None if data.get("profile") is None else str(data["profile"]),
            set_values=tuple(str(item) for item in set_values),
            block_values=tuple(str(item) for item in block_values),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkPlan:
    pipeline: Path
    repeat: int = 3
    warmup: int = 1
    variants: tuple[BenchmarkVariant, ...] = field(default_factory=lambda: (BenchmarkVariant("default"),))
    source: Path | None = None

    def __post_init__(self) -> None:
        if self.repeat < 1:
            raise ValueError("Benchmark repeat must be at least 1")
        if self.warmup < 0:
            raise ValueError("Benchmark warmup cannot be negative")
        if not self.variants:
            raise ValueError("Benchmark plan requires at least one variant")
        names = [variant.name for variant in self.variants]
        if len(names) != len(set(names)):
            raise ValueError("Benchmark variant names must be unique")


def load_benchmark_plan(
    spec: str | Path,
    *,
    pipeline_override: str | Path | None = None,
    repeat_override: int | None = None,
    warmup_override: int | None = None,
    selected_variants: Sequence[str] | None = None,
) -> BenchmarkPlan:
    spec_path = Path(spec).expanduser().resolve()
    raw = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Benchmark specification must be a YAML mapping")
    version = raw.get("version", 1)
    if version != 1:
        raise ValueError(f"Unsupported benchmark specification version: {version!r}")
    pipeline_value = pipeline_override or raw.get("pipeline")
    if pipeline_value is None:
        raise ValueError("Benchmark specification requires pipeline: path/to/pipeline.yaml")
    pipeline = Path(pipeline_value).expanduser()
    if not pipeline.is_absolute():
        pipeline = (spec_path.parent / pipeline).resolve()
    if not pipeline.is_file():
        raise FileNotFoundError(f"Benchmark pipeline does not exist: {pipeline}")

    variants_raw = raw.get("variants") or {"default": {}}
    if not isinstance(variants_raw, dict):
        raise ValueError("Benchmark variants must be a YAML mapping")
    requested = set(selected_variants or ())
    unknown = sorted(requested - set(variants_raw))
    if unknown:
        raise ValueError(f"Unknown benchmark variants: {', '.join(unknown)}")
    variants = tuple(
        BenchmarkVariant.from_mapping(str(name), value)
        for name, value in variants_raw.items()
        if not requested or name in requested
    )
    return BenchmarkPlan(
        pipeline=pipeline,
        repeat=int(repeat_override if repeat_override is not None else raw.get("repeat", 3)),
        warmup=int(warmup_override if warmup_override is not None else raw.get("warmup", 1)),
        variants=variants,
        source=spec_path,
    )


def direct_benchmark_plan(
    pipeline: str | Path,
    *,
    repeat: int = 3,
    warmup: int = 1,
    profile: str | None = None,
    set_values: Sequence[str] | None = None,
    block_values: Sequence[str] | None = None,
) -> BenchmarkPlan:
    path = Path(pipeline).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Benchmark pipeline does not exist: {path}")
    return BenchmarkPlan(
        pipeline=path,
        repeat=repeat,
        warmup=warmup,
        variants=(BenchmarkVariant("default", profile, tuple(set_values or ()), tuple(block_values or ())),),
    )


def _node_metric(report: Mapping[str, Any], node_name: str, dotted: str) -> float:
    current: Any = dict(report.get("nodes") or {}).get(node_name, {})
    for part in dotted.split("."):
        if not isinstance(current, Mapping):
            return 0.0
        current = current.get(part)
    try:
        return float(current or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _terminal_nodes(report: Mapping[str, Any]) -> list[str]:
    nodes = set(dict(report.get("nodes") or {}))
    producers = {
        str(edge.get("source", "")).split(".", 1)[0]
        for edge in list(report.get("edges") or [])
        if isinstance(edge, Mapping)
    }
    terminals = sorted(nodes - producers)
    return terminals or sorted(nodes)


def _memory_bytes(node: Mapping[str, Any]) -> int:
    resources = dict(node.get("resources") or {})
    values = (
        resources.get("rss_bytes"),
        resources.get("executor_rss_bytes"),
        resources.get("shared_buffer_bytes"),
        resources.get("estimated_queue_bytes"),
    )
    total = 0
    for value in values:
        try:
            total += max(0, int(value or 0))
        except (TypeError, ValueError):
            continue
    return total


def aggregate_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not reports:
        raise ValueError("Cannot aggregate an empty benchmark report list")
    node_names = sorted({name for report in reports for name in dict(report.get("nodes") or {})})
    nodes: dict[str, Any] = {}
    for name in node_names:
        nodes[name] = {
            "messages": _summary(_node_metric(report, name, "messages") for report in reports),
            "rate_hz": _summary(_node_metric(report, name, "rate_hz") for report in reports),
            "processing_ms": {
                "mean": _summary(
                    _node_metric(report, name, "processing.mean_ms")
                    or _node_metric(report, name, "mean_ms")
                    for report in reports
                ),
                "p50": _summary(
                    _node_metric(report, name, "processing.p50_ms")
                    or _node_metric(report, name, "p50_ms")
                    for report in reports
                ),
                "p95": _summary(
                    _node_metric(report, name, "processing.p95_ms")
                    or _node_metric(report, name, "p95_ms")
                    for report in reports
                ),
                "p99": _summary(
                    _node_metric(report, name, "processing.p99_ms")
                    or _node_metric(report, name, "p99_ms")
                    for report in reports
                ),
            },
            "queue_wait_p95_ms": _summary(_node_metric(report, name, "queue_wait.p95_ms") for report in reports),
            "end_to_end_p95_ms": _summary(_node_metric(report, name, "end_to_end.p95_ms") for report in reports),
            "errors": _summary(_node_metric(report, name, "errors") for report in reports),
        }

    durations = [float(report.get("duration_seconds") or 0.0) for report in reports]
    source_rates: list[float] = []
    sink_rates: list[float] = []
    e2e_p95: list[float] = []
    drops: list[float] = []
    errors: list[float] = []
    memory: list[float] = []
    temperatures: list[float] = []
    for report in reports:
        report_nodes = dict(report.get("nodes") or {})
        rates = [float(dict(value).get("rate_hz") or 0.0) for value in report_nodes.values()]
        source_rates.append(max(rates, default=0.0))
        terminals = _terminal_nodes(report)
        terminal_rates = [float(dict(report_nodes.get(name) or {}).get("rate_hz") or 0.0) for name in terminals]
        sink_rates.append(min((rate for rate in terminal_rates if rate > 0.0), default=0.0))
        e2e_p95.append(max((_node_metric(report, name, "end_to_end.p95_ms") for name in report_nodes), default=0.0))
        drops.append(sum(float(dict(edge).get("dropped") or 0.0) for edge in list(report.get("edges") or [])))
        errors.append(sum(float(dict(value).get("errors") or 0.0) for value in report_nodes.values()))
        memory.append(sum(_memory_bytes(dict(value)) for value in report_nodes.values()))
        system = dict(report.get("system") or {})
        try:
            temperature = float(system.get("temperature_c"))
        except (TypeError, ValueError):
            temperature = 0.0
        if temperature > 0.0:
            temperatures.append(temperature)

    return {
        "pipeline": reports[0].get("pipeline"),
        "successful_runs": sum(1 for report in reports if report.get("status") in {"completed", "stopped"}),
        "runs": len(reports),
        "duration_seconds": _summary(durations),
        "source_rate_hz": _summary(source_rates),
        "sink_rate_hz": _summary(sink_rates),
        "end_to_end_p95_ms": _summary(e2e_p95),
        "dropped_messages": _summary(drops),
        "errors": _summary(errors),
        "estimated_memory_bytes": _summary(memory),
        "temperature_c": _summary(temperatures),
        "nodes": nodes,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk_model_values(value: Any, *, key: str = "") -> Iterable[str]:
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            yield from _walk_model_values(child, key=str(child_key).lower())
    elif isinstance(value, list):
        for child in value:
            yield from _walk_model_values(child, key=key)
    elif isinstance(value, str) and any(token in key for token in ("model", "weights", "param", "engine", "onnx")):
        yield value


def model_inventory(document: Path, *, base_dir: Path | None = None) -> list[dict[str, Any]]:
    try:
        raw = yaml.safe_load(document.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    candidates = list(_walk_model_values(raw))
    blocks = dict(raw.get("blocks") or {}) if isinstance(raw, Mapping) else {}
    for block in blocks.values():
        block_path = (document.parent / str(block)).resolve()
        if not block_path.is_file():
            continue
        try:
            block_raw = yaml.safe_load(block_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        candidates.extend(_walk_model_values(block_raw))
    result: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for value in candidates:
        if "${" in value or "://" in value:
            continue
        path = Path(os.path.expandvars(value)).expanduser()
        if not path.is_absolute():
            path = ((base_dir or document.parent) / path).resolve()
        paths: list[Path]
        if path.is_dir():
            supported = {".param", ".bin", ".onnx", ".engine", ".xml"}
            paths = sorted(
                item for item in path.iterdir()
                if item.is_file() and item.suffix.lower() in supported
            )
        else:
            paths = [path]
        for item in paths:
            if item in seen or not item.is_file():
                continue
            seen.add(item)
            result.append({"path": str(item), "size_bytes": item.stat().st_size, "sha256": _sha256_file(item)})
    return result


def environment_snapshot() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "environment": {
            key: value
            for key, value in sorted(os.environ.items())
            if key.startswith("NODRIX_")
            and not any(token in key.upper() for token in ("TOKEN", "SECRET", "PASSWORD", "KEY"))
        },
    }


def run_benchmark_suite(
    plan: BenchmarkPlan,
    runner: RunCallable,
    *,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    root = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else plan.pipeline.parent / ".nodrix" / "benchmarks"
    )
    suite_dir = root / f"{stamp}-{_safe_name(plan.pipeline.stem)}"
    suite_dir.mkdir(parents=True, exist_ok=False)
    _json_write(suite_dir / "environment.json", environment_snapshot())
    if plan.source is not None:
        (suite_dir / "benchmark.yaml").write_text(plan.source.read_text(encoding="utf-8"), encoding="utf-8")

    variant_results: dict[str, Any] = {}
    measured_run_dirs: list[Path] = []
    for variant in plan.variants:
        variant_dir = suite_dir / "variants" / _safe_name(variant.name)
        run_root = variant_dir / "runs"
        warmup_root = variant_dir / "warmup"
        warmup_runs: list[str] = []
        for _ in range(plan.warmup):
            report = dict(runner(
                plan.pipeline,
                warmup_root,
                variant.profile,
                list(variant.set_values),
                list(variant.block_values),
            ))
            warmup_runs.append(str(report.get("run_dir") or ""))
        reports = [
            dict(runner(plan.pipeline, run_root, variant.profile, list(variant.set_values), list(variant.block_values)))
            for _ in range(plan.repeat)
        ]
        measured_run_dirs.extend(
            Path(str(report.get("run_dir"))).resolve()
            for report in reports
            if report.get("run_dir")
        )
        summary = aggregate_reports(reports)
        summary.update({
            "schema": BENCHMARK_SCHEMA,
            "variant": variant.name,
            "profile": variant.profile,
            "set": list(variant.set_values),
            "block": list(variant.block_values),
            "repeat": plan.repeat,
            "warmup": plan.warmup,
            "run_dirs": [str(report.get("run_dir") or "") for report in reports],
            "warmup_run_dirs": warmup_runs,
        })
        _json_write(variant_dir / "summary.json", summary)
        variant_results[variant.name] = summary

    inventory = model_inventory(plan.pipeline)
    known_models = {str(item["path"]): item for item in inventory}
    for run_dir in measured_run_dirs:
        resolved = run_dir / "resolved-manifest.yaml"
        if not resolved.is_file():
            resolved = run_dir / "manifest.resolved.yaml"
        if not resolved.is_file():
            continue
        for item in model_inventory(resolved, base_dir=plan.pipeline.parent):
            known_models[str(item["path"])] = item
    _json_write(suite_dir / "models.json", list(known_models.values()))

    suite = {
        "schema": BENCHMARK_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pipeline": str(plan.pipeline),
        "suite_dir": str(suite_dir),
        "repeat": plan.repeat,
        "warmup": plan.warmup,
        "variants": variant_results,
    }
    _json_write(suite_dir / "benchmark.json", suite)
    return suite


def replay_plan(run_dir: str | Path) -> dict[str, Any]:
    directory = Path(run_dir).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"Run directory does not exist: {directory}")
    recordings = sorted(directory.rglob("*.ndrx"))
    if recordings:
        return {
            "replayable": True,
            "mode": "recording",
            "recording": str(recordings[0]),
            "command": ["nodrix", "play", str(recordings[0])],
            "reason": "A captured .ndrx input is available.",
        }
    manifest = directory / "resolved-manifest.yaml"
    if not manifest.is_file():
        manifest = directory / "manifest.resolved.yaml"
    if not manifest.is_file():
        return {
            "replayable": False,
            "mode": "unavailable",
            "command": [],
            "reason": "No resolved manifest or .ndrx recording is available.",
        }
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    text = json.dumps(raw, default=str).lower()
    live_markers = (
        "rtsp://",
        "http://",
        "https://",
        "srt://",
        "/dev/video",
        "v4l2_source",
        "csi_source",
        "rtsp_source",
    )
    if any(marker in text for marker in live_markers):
        return {
            "replayable": False,
            "mode": "live-source",
            "manifest": str(manifest),
            "command": [],
            "reason": "The run references a live source. Record it to .ndrx before deterministic replay.",
        }
    return {
        "replayable": True,
        "mode": "manifest",
        "manifest": str(manifest),
        "command": ["nodrix", "run", str(manifest)],
        "reason": (
            "The resolved manifest contains no recognized live-source URI. "
            "Relative assets may still require the original project directory."
        ),
    }
