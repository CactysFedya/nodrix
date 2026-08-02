from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping

import yaml

from .execution_plan import compile_execution_plan
from .manifest import ManifestLoadResult, PipelineManifest, canonical_config_path
from .provenance import hardware_snapshot


PLANNER_SCHEMA = "nodrix.plan/v1"
DIAGNOSIS_SCHEMA = "nodrix.diagnosis/v1"
OPTIMIZATION_SCHEMA = "nodrix.optimization/v1"


def _topological_order(manifest: PipelineManifest) -> list[str]:
    incoming = {name: 0 for name in manifest.nodes}
    outgoing: dict[str, list[str]] = {name: [] for name in manifest.nodes}
    for edge in manifest.edges:
        source = edge.source.split(".", 1)[0]
        target = edge.target.split(".", 1)[0]
        if source in outgoing and target in incoming:
            outgoing[source].append(target)
            incoming[target] += 1
    ready = [name for name in manifest.nodes if incoming[name] == 0]
    order: list[str] = []
    while ready:
        name = ready.pop(0)
        order.append(name)
        for target in outgoing[name]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    return order + [name for name in manifest.nodes if name not in order]


def _positive_number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _declared_source_rate(parameters: Mapping[str, Any]) -> tuple[float | None, str]:
    for key in ("fps", "rate_hz", "frequency_hz", "hz"):
        value = _positive_number(parameters.get(key))
        if value is not None:
            return value, f"nodes.*.parameters.{key}"
    interval = _positive_number(parameters.get("interval"))
    if interval is None:
        interval = _positive_number(parameters.get("interval_seconds"))
    if interval is not None:
        return 1.0 / interval, "nodes.*.parameters.interval"
    return None, "not declared"


def _rate_plan(manifest: PipelineManifest) -> tuple[dict[str, dict[str, Any]], float | None]:
    incoming: dict[str, list[str]] = {name: [] for name in manifest.nodes}
    outgoing: dict[str, list[str]] = {name: [] for name in manifest.nodes}
    for edge in manifest.edges:
        source = edge.source.split(".", 1)[0]
        target = edge.target.split(".", 1)[0]
        incoming.setdefault(target, []).append(source)
        outgoing.setdefault(source, []).append(target)
    rates: dict[str, dict[str, Any]] = {}
    for name in _topological_order(manifest):
        parameters = manifest.nodes[name].parameters
        parents = [rates[parent]["estimated_hz"] for parent in incoming.get(name, ()) if parent in rates]
        known_parents = [float(value) for value in parents if value is not None]
        if not incoming.get(name):
            rate, basis = _declared_source_rate(parameters)
        elif len(known_parents) == len(parents) and known_parents:
            rate = min(known_parents)
            basis = "minimum known upstream rate"
        else:
            rate = None
            basis = "upstream rate is not measured or declared"
        divisor = None
        for key in ("every_n", "detect_every_n", "sample_every"):
            candidate = _positive_number(parameters.get(key))
            if candidate is not None:
                divisor = max(1.0, candidate)
                basis += f"; divided by {key}={candidate:g}"
                break
        if rate is not None and divisor is not None:
            rate /= divisor
        rates[name] = {
            "estimated_hz": rate,
            "basis": basis,
            "confidence": "configured" if rate is not None else "unknown",
        }
    terminals = [name for name in manifest.nodes if not outgoing.get(name)]
    terminal_rates = [rates[name]["estimated_hz"] for name in terminals]
    expected = (
        min(float(value) for value in terminal_rates if value is not None)
        if terminal_rates and all(value is not None for value in terminal_rates)
        else None
    )
    return rates, expected


def _backend_decisions(manifest: PipelineManifest) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for name, config in manifest.nodes.items():
        parameters = config.parameters
        if config.uses == "media.ffmpeg_encoder":
            from .media import select_encoder

            try:
                selection = select_encoder(
                    str(parameters.get("codec", "h264")),
                    str(parameters.get("encoder", "auto")),
                    str(parameters.get("acceleration", "preferred")),
                )
                decisions.append(
                    {
                        "target": f"{name}.backend",
                        "selected": selection.get("encoder"),
                        "available": bool(selection.get("ok")),
                        "reason": selection.get("reason"),
                        "fallback": selection.get("fallback"),
                        "rejected": list(selection.get("attempts") or []),
                        "evidence": "runtime FFmpeg encoder probes",
                    }
                )
            except Exception as exc:
                decisions.append(
                    {
                        "target": f"{name}.backend",
                        "selected": None,
                        "available": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                        "fallback": None,
                        "rejected": [],
                        "evidence": "probe failed",
                    }
                )
        elif "acceleration" in parameters or "backend" in parameters:
            decisions.append(
                {
                    "target": f"{name}.backend",
                    "selected": parameters.get("backend", "auto"),
                    "available": None,
                    "reason": "Final backend is selected and probed when the node opens.",
                    "fallback": None,
                    "rejected": [],
                    "evidence": "configuration only; no performance claim",
                }
            )
    return decisions


def build_static_plan(
    manifest: PipelineManifest,
    description: dict[str, Any],
    *,
    include_hardware: bool = True,
) -> dict[str, Any]:
    execution = compile_execution_plan(manifest, description)
    rates, expected = _rate_plan(manifest)
    backend_decisions = _backend_decisions(manifest)
    recommendations: list[dict[str, Any]] = []
    for edge in description.get("edges", []):
        memory = dict(edge.get("memory") or {})
        copies = int(memory.get("planned_copies", 0))
        if copies:
            recommendations.append(
                {
                    "code": "P201",
                    "target": f"{edge.get('from')}:{edge.get('to')}",
                    "message": f"Remove or benchmark {copies} planned payload copy/copies.",
                    "evidence": memory.get("reason", "memory-domain negotiation"),
                }
            )
    for decision in backend_decisions:
        if decision.get("fallback"):
            recommendations.append(
                {
                    "code": "P301",
                    "target": decision["target"],
                    "message": f"Software fallback {decision['fallback']} is selected.",
                    "evidence": decision.get("reason"),
                }
            )
        if decision.get("available") is False:
            recommendations.append(
                {
                    "code": "P302",
                    "target": decision["target"],
                    "message": "Configured backend cannot start on this host.",
                    "evidence": decision.get("reason"),
                }
            )
    if expected is None:
        recommendations.append(
            {
                "code": "P101",
                "target": "pipeline.throughput",
                "message": "Run `plyctl benchmark` before assigning an output FPS target.",
                "evidence": "At least one source or processing rate is unknown.",
            }
        )
    return {
        "schema": PLANNER_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pipeline": manifest.metadata.name,
        "engine": description.get("engine", "unified"),
        "hardware": hardware_snapshot() if include_hardware else None,
        "execution_plan": execution,
        "rates": rates,
        "expected_output_hz": expected,
        "expected_output_basis": (
            "configured terminal rates"
            if expected is not None
            else "unknown until measured"
        ),
        "backend_decisions": backend_decisions,
        "recommendations": recommendations,
    }


def _metric(node: Mapping[str, Any], *paths: str) -> float:
    for path in paths:
        value: Any = node
        for part in path.split("."):
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(part)
        number = _positive_number(value)
        if number is not None:
            return number
    return 0.0


def diagnose_report(report: Mapping[str, Any]) -> dict[str, Any]:
    nodes = {str(name): dict(value) for name, value in dict(report.get("nodes") or {}).items()}
    edges = [dict(value) for value in list(report.get("edges") or [])]
    findings: list[dict[str, Any]] = []
    processing = {
        name: _metric(node, "processing.p95_ms", "p95_ms")
        for name, node in nodes.items()
    }
    if any(processing.values()):
        name = max(processing, key=processing.get)
        findings.append(
            {
                "severity": "info",
                "code": "D101",
                "target": name,
                "message": "Highest measured node processing P95.",
                "evidence": {"p95_ms": processing[name]},
                "recommendation": "Benchmark alternatives for this node before tuning other stages.",
            }
        )
    for edge in edges:
        capacity = max(int(edge.get("capacity", 0)), 1)
        pressure = max(int(edge.get("depth", 0)), int(edge.get("max_depth", 0))) / capacity
        dropped = int(edge.get("dropped", 0))
        target = f"{edge.get('source', edge.get('from'))}:{edge.get('target', edge.get('to'))}"
        if pressure >= 0.8 or dropped:
            findings.append(
                {
                    "severity": "warning",
                    "code": "D201",
                    "target": target,
                    "message": "Measured queue pressure or message drops.",
                    "evidence": {
                        "pressure": min(pressure, 1.0),
                        "dropped": dropped,
                        "policy": edge.get("policy"),
                    },
                    "recommendation": (
                        "Reduce producer rate or accelerate the consumer; enlarge the queue only after latency measurement."
                    ),
                }
            )
        memory = dict(edge.get("memory") or {})
        if int(memory.get("planned_copies", 0)):
            findings.append(
                {
                    "severity": "warning",
                    "code": "D301",
                    "target": target,
                    "message": "The edge contains planned memory copies.",
                    "evidence": memory,
                    "recommendation": "Select a common memory domain or add an explicit measured adapter.",
                }
            )
    for name, node in nodes.items():
        resources = dict(node.get("resources") or {})
        transport = dict(node.get("transport") or {})
        runtime_info = dict(node.get("runtime_info") or {})
        copies = int(transport.get("input_payload_copies", 0)) + int(
            transport.get("output_payload_copies", 0)
        )
        if copies:
            findings.append(
                {
                    "severity": "warning",
                    "code": "D302",
                    "target": name,
                    "message": "Runtime payload copies were measured.",
                    "evidence": {"copies": copies},
                    "recommendation": "Inspect process boundaries and buffer ownership.",
                }
            )
        if runtime_info.get("fallback"):
            findings.append(
                {
                    "severity": "warning",
                    "code": "D401",
                    "target": name,
                    "message": "A software fallback was used.",
                    "evidence": runtime_info,
                    "recommendation": "Install/probe the intended hardware backend or set acceleration: disabled explicitly.",
                }
            )
        if int(resources.get("sync_misses", 0)):
            findings.append(
                {
                    "severity": "warning",
                    "code": "D202",
                    "target": name,
                    "message": "Synchronization misses were measured.",
                    "evidence": {"sync_misses": int(resources["sync_misses"])},
                    "recommendation": "Review trigger_port, optional inputs, and timestamp tolerance.",
                }
            )
    system = dict(report.get("system") or {})
    temperature = _positive_number(system.get("temperature_c"))
    if temperature is not None and temperature >= 80:
        findings.append(
            {
                "severity": "warning",
                "code": "D501",
                "target": "system.temperature",
                "message": "High temperature may throttle the pipeline.",
                "evidence": {"temperature_c": temperature, "throttled": system.get("throttled")},
                "recommendation": "Improve cooling or lower the sustained workload, then repeat the benchmark.",
            }
        )
    return {
        "schema": DIAGNOSIS_SCHEMA,
        "pipeline": report.get("pipeline"),
        "status": report.get("status"),
        "duration_seconds": report.get("duration_seconds"),
        "measured": bool(nodes),
        "findings": findings,
        "summary": {
            "warnings": sum(item["severity"] == "warning" for item in findings),
            "findings": len(findings),
        },
    }


def _config_value(document: Mapping[str, Any], dotted: str) -> Any:
    value: Any = document
    for part in dotted.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise KeyError(dotted)
        value = value[part]
    return value


def explain_target(
    details: ManifestLoadResult,
    description: dict[str, Any],
    target: str,
) -> dict[str, Any]:
    target = target.strip()
    plan = build_static_plan(details.manifest, description, include_hardware=False)
    if target.startswith("edge "):
        reference = target.removeprefix("edge ").strip()
        source, separator, destination = reference.partition(":")
        if not separator:
            raise ValueError("Edge explanation must use edge SOURCE:TARGET")
        for edge in description.get("edges", []):
            if edge.get("from") == source and edge.get("to") == destination:
                return {
                    "kind": "edge",
                    "target": reference,
                    "value": edge,
                    "source": "memory and queue negotiation",
                    "reason": dict(edge.get("memory") or {}).get("reason"),
                    "rejected": dict(edge.get("memory") or {}).get("transfers", []),
                }
        raise KeyError(f"Unknown edge: {reference}")
    if target in details.manifest.nodes:
        config = details.manifest.nodes[target]
        described = dict(description.get("nodes") or {}).get(target, {})
        return {
            "kind": "node",
            "target": target,
            "value": {
                "uses": config.uses,
                "implementation": described.get("implementation"),
                "device": config.execution.device,
                "isolation": config.execution.isolation,
            },
            "source": details.sources.get(f"nodes.{target}.uses", "manifest/schema"),
            "reason": "Resolved node implementation and execution policy.",
            "rejected": [],
        }
    for decision in plan["backend_decisions"]:
        if decision["target"] == target:
            return {"kind": "backend", **decision}
    canonical = canonical_config_path(target, details.manifest.nodes)
    value = _config_value(details.canonical, canonical)
    return {
        "kind": "config",
        "target": canonical,
        "value": value,
        "source": details.sources.get(canonical, "built-in schema default"),
        "reason": "Profile, block, manifest, and CLI overrides are applied in deterministic order.",
        "rejected": [],
    }


def optimization_spec(
    manifest: PipelineManifest,
    *,
    max_variants: int = 12,
    objectives: Mapping[str, Any] | None = None,
    constraints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    variants: dict[str, dict[str, list[str]]] = {"baseline": {"set": []}}
    cpu_count = max(os.cpu_count() or 1, 1)
    for name, config in manifest.nodes.items():
        parameters = config.parameters
        if "threads" in parameters:
            current = max(int(parameters["threads"]), 1)
            for candidate in sorted({max(1, current - 1), current + 1, min(cpu_count, current * 2)}):
                if candidate == current or len(variants) >= max_variants:
                    continue
                variants[f"{name}_threads_{candidate}"] = {
                    "set": [f"{name}.threads={candidate}"]
                }
        for key in ("every_n", "detect_every_n", "sample_every"):
            if key not in parameters:
                continue
            current = max(int(parameters[key]), 1)
            for candidate in sorted({max(1, current - 1), current + 1}):
                if candidate == current or len(variants) >= max_variants:
                    continue
                variants[f"{name}_{key}_{candidate}"] = {
                    "set": [f"{name}.{key}={candidate}"]
                }
    return {
        "schema": OPTIMIZATION_SCHEMA,
        "pipeline": manifest.metadata.name,
        "objectives": dict(objectives or {"maximize": "output_fps"}),
        "constraints": dict(constraints or {}),
        "variants": variants,
        "applied": False,
        "note": "Candidates are separate benchmark variants; the source manifest is unchanged.",
    }


def select_optimization_variant(
    benchmark: Mapping[str, Any],
    *,
    constraints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    limits = dict(constraints or {})
    candidates: list[dict[str, Any]] = []
    for name, raw in dict(benchmark.get("variants") or {}).items():
        item = dict(raw)
        rate = float(dict(item.get("sink_rate_hz") or {}).get("mean", 0.0))
        latency = float(dict(item.get("end_to_end_p95_ms") or {}).get("mean", 0.0))
        temperature = float(dict(item.get("temperature_c") or {}).get("max", 0.0))
        memory_mb = float(
            dict(item.get("estimated_memory_bytes") or {}).get("max", 0.0)
        ) / (1024 * 1024)
        violations: list[str] = []
        if limits.get("latency_p95_ms") is not None and latency > float(
            limits["latency_p95_ms"]
        ):
            violations.append("latency_p95_ms")
        if limits.get("temperature_c") is not None and temperature > float(
            limits["temperature_c"]
        ):
            violations.append("temperature_c")
        if limits.get("memory_mb") is not None and memory_mb > float(
            limits["memory_mb"]
        ):
            violations.append("memory_mb")
        candidates.append(
            {
                "variant": name,
                "output_fps": rate,
                "latency_p95_ms": latency,
                "temperature_c": temperature,
                "memory_mb": memory_mb,
                "eligible": not violations,
                "violations": violations,
            }
        )
    eligible = [item for item in candidates if item["eligible"]]
    selected = max(eligible, key=lambda item: item["output_fps"]) if eligible else None
    return {
        "selected": None if selected is None else selected["variant"],
        "reason": (
            "Highest measured sink throughput satisfying every constraint."
            if selected is not None
            else "No measured variant satisfied every constraint."
        ),
        "candidates": candidates,
        "applied": False,
    }


def write_optimization_bundle(
    pipeline: Path,
    manifest: PipelineManifest,
    output_dir: Path,
    *,
    max_variants: int = 12,
    objectives: Mapping[str, Any] | None = None,
    constraints: Mapping[str, Any] | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = optimization_spec(
        manifest,
        max_variants=max_variants,
        objectives=objectives,
        constraints=constraints,
    )
    spec = {
        "version": 1,
        "pipeline": str(pipeline.resolve()),
        "warmup": 1,
        "repeat": 3,
        "variants": result["variants"],
    }
    spec_path = output_dir / "benchmark-variants.yaml"
    report_path = output_dir / "optimization-plan.json"
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    report_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return spec_path, report_path, result
