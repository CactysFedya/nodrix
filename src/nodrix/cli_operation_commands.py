from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

from rich.table import Table
import typer
import yaml

from .benchmarking import (
    direct_benchmark_plan,
    load_benchmark_plan,
)
from .benchmark_operation import (
    execute_benchmark_operation,
)
from .cli_context import (
    _format_bytes,
    _runtime,
    app,
    console,
    data_app,
    device_app,
    media_app,
    recording_app,
)
from .hybrid_runtime import HybridPipelineRuntime
from .manifest import load_manifest_details
from .optimization import (
    build_optimization_plan,
)
from .optimization_operation import (
    execute_optimization_operation,
)
from .planning import (
    build_static_plan,
    diagnose_report,
    explain_target,
)
from .storage_layout import StorageLayout


@recording_app.command("info")
def recording_info(recording: Annotated[Path, typer.Argument(exists=True, readable=True)]) -> None:
    """Show streams, types, counts, and size of an .ndrx file."""
    from .recording import NdrxReader, RecordingError

    try:
        with NdrxReader(recording) as reader:
            info = reader.info()
    except (OSError, ValueError, RecordingError) as exc:
        console.print(f"[red]Cannot read recording:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[bold]{info['path']}[/bold]  messages={info['messages']} size={info['size_bytes']} bytes")
    table = Table("Stream", "Type", "Messages")
    for name, spec in info.get("streams", {}).items():
        table.add_row(name or "(unnamed)", str(spec.get("type", "core.any")), str(spec.get("messages", 0)))
    console.print(table)


@recording_app.command("repair")
def recording_repair(
    recording: Annotated[Path, typer.Argument(exists=True, readable=True)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    checkpoint_records: Annotated[int, typer.Option("--checkpoint-records", min=1)] = 1024,
) -> None:
    """Recover complete records and write a finalized NDRX2 file."""
    from .recording import RecordingError, repair_recording

    try:
        info = repair_recording(
            recording,
            output,
            checkpoint_records=checkpoint_records,
        )
    except (OSError, ValueError, RecordingError) as exc:
        console.print(f"[red]Cannot repair recording:[/red] {exc}")
        raise typer.Exit(1)
    console.print(
        f"[green]Repaired[/green] {info['messages']} messages to {info['path']}"
    )


@data_app.command("doctor")
def data_plane_doctor() -> None:
    """Verify POSIX shared memory and report the active IPC capabilities."""
    from .shared_memory import SharedBufferPool
    try:
        with SharedBufferPool(4096, 2) as pool:
            value = pool.acquire(16)
            value.memoryview()[:4] = b"NDRX"
            ok = bytes(value.memoryview()[:4]) == b"NDRX"
            stats = pool.stats()
            value.release()
    except Exception as exc:
        console.print(f"[red]Shared memory unavailable:[/red] {exc}")
        raise typer.Exit(1)
    table = Table("Capability", "Status")
    table.add_row("POSIX shared memory", "yes" if ok else "no")
    table.add_row("Process isolation", "yes")
    table.add_row("Descriptor-only transfer", "yes for SharedBufferPool payloads")
    table.add_row("Pool segment", str(stats.get("name")))
    console.print(table)


@device_app.command("doctor")
def device_memory_doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON")] = False,
) -> None:
    """Report native device-memory, DLPack, V4L2 and libav capabilities."""
    from .device import device_doctor

    info = device_doctor()
    if json_output:
        console.print_json(json.dumps(info))
        return
    table = Table("Capability", "Status")
    labels = {
        "native_extension": "Native device extension",
        "v4l2_headers": "V4L2 native API",
        "dma_heap": "Linux DMA heap",
        "dri": "DRM render devices",
        "libavformat": "Native libavformat",
        "libavcodec": "Native libavcodec",
        "cuda_runtime": "CUDA runtime",
        "opencl_runtime": "OpenCL runtime",
        "vulkan_runtime": "Vulkan runtime",
        "dlpack_numpy": "NumPy DLPack",
        "dlpack_torch": "PyTorch DLPack",
        "dlpack_cupy": "CuPy DLPack",
        "dma_buf_descriptor": "DMA-BUF descriptors",
        "cuda_ipc_descriptor": "CUDA IPC descriptors",
    }
    for key, label in labels.items():
        value = info.get(key, False)
        table.add_row(label, "yes" if value is True else "no" if value is False else str(value))
    console.print(table)


@device_app.command("v4l2-probe")
def device_v4l2_probe(
    device: Annotated[str, typer.Argument(help="Linux V4L2 path")] = "/dev/video0",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Query a V4L2 device through the native extension without starting capture."""
    from .device import probe_v4l2

    try:
        info = probe_v4l2(device)
    except Exception as exc:
        console.print(f"[red]V4L2 probe failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(info))
        return
    table = Table("Field", "Value")
    for key, value in info.items():
        table.add_row(str(key), str(value))
    console.print(table)


def _execute_benchmark_run(
    pipeline: Path,
    run_root: Path,
    profile: str | None,
    set_values: list[str],
    block_values: list[str],
) -> dict[str, object]:
    runtime = _runtime(
        pipeline,
        run_root=run_root,
        profile=profile,
        overrides=set_values,
        block_overrides=block_values,
    )
    return runtime.run_sync() if isinstance(runtime, HybridPipelineRuntime) else asyncio.run(runtime.run())


@app.command()
def benchmark(
    pipeline: Annotated[Path | None, typer.Argument(help="2.x Pipeline manifest; defaults to pipeline.yaml")] = None,
    spec: Annotated[Path | None, typer.Option("--spec", help="Versioned benchmark YAML specification")] = None,
    repeat: Annotated[int | None, typer.Option("--repeat", min=1)] = None,
    warmup: Annotated[int | None, typer.Option("--warmup", min=0)] = None,
    output: Annotated[Path | None, typer.Option("--output", help="Benchmark artifact root or legacy summary .json path")] = None,
    variants: Annotated[list[str] | None, typer.Option("--variant", help="Run only a named variant from --spec")] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run a reproducible benchmark suite with warm-up, variants, artifacts and percentiles."""
    try:
        if spec is not None:
            plan = load_benchmark_plan(
                spec,
                pipeline_override=pipeline,
                repeat_override=repeat,
                warmup_override=warmup,
                selected_variants=variants,
            )
            if profile is not None or set_values or block_values:
                raise ValueError("--profile, --set and --block belong in benchmark variants when --spec is used")
        else:
            plan = direct_benchmark_plan(
                pipeline or Path("pipeline.yaml"),
                repeat=repeat if repeat is not None else 3,
                warmup=warmup if warmup is not None else 1,
                profile=profile,
                set_values=set_values,
                block_values=block_values,
            )
        legacy_json = output if output is not None and output.suffix.lower() == ".json" else None
        root = output.parent if legacy_json is not None else output
        outcome = execute_benchmark_operation(
            plan,
            run_callable=_execute_benchmark_run,
            output_root=root,
        )

        if not outcome.successful:
            message = outcome.execution.details.get(
                "error",
                "benchmark execution failed",
            )
            raise RuntimeError(str(message))

        summary = outcome.summary()

        if legacy_json is not None:
            legacy_json.parent.mkdir(parents=True, exist_ok=True)
            legacy_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        console.print(f"[red]Benchmark failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(summary))
        return
    table = Table("Variant", "Runs", "Source Hz", "Sink Hz", "E2E P95 ms", "Drops", "Memory")
    for name, raw in dict(summary.get("variants", {})).items():
        item = dict(raw)
        table.add_row(
            str(name),
            str(item.get("runs", 0)),
            f"{float(dict(item.get('source_rate_hz') or {}).get('mean', 0.0)):.2f}",
            f"{float(dict(item.get('sink_rate_hz') or {}).get('mean', 0.0)):.2f}",
            f"{float(dict(item.get('end_to_end_p95_ms') or {}).get('mean', 0.0)):.3f}",
            f"{float(dict(item.get('dropped_messages') or {}).get('mean', 0.0)):.1f}",
            _format_bytes(dict(item.get("estimated_memory_bytes") or {}).get("mean")),
        )
    console.print(table)
    console.print(f"Artifacts: {summary['suite_dir']}")


@app.command("plan")
def plan_command(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)] = Path("pipeline.yaml"),
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Plan rates, memory paths, queues, and probed hardware without running the graph."""
    try:
        details = load_manifest_details(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        runtime = _runtime(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        result = build_static_plan(details.manifest, runtime.describe())
    except Exception as exc:
        console.print(f"[red]Planning failed:[/red] {exc}")
        raise typer.Exit(1)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        console.print(f"[green]Written[/green] {output.resolve()}")
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False))
        return
    table = Table("Node", "Configured estimate", "Basis")
    for name, raw in result["rates"].items():
        rate = raw.get("estimated_hz")
        table.add_row(
            name,
            f"{float(rate):.2f} Hz" if rate is not None else "unknown",
            str(raw.get("basis", "")),
        )
    console.print(table)
    expected = result.get("expected_output_hz")
    console.print(
        "Expected output: "
        + (f"{float(expected):.2f} Hz" if expected is not None else "unknown until measured")
    )
    for decision in result["backend_decisions"]:
        console.print(
            f"{decision['target']}: {decision.get('selected') or 'unavailable'}"
            f" · {decision.get('reason')}"
        )
    for recommendation in result["recommendations"]:
        console.print(
            f"[yellow]{recommendation['code']}[/yellow] "
            f"{recommendation['target']}: {recommendation['message']}"
        )


def _latest_run_report(root: Path) -> Path:
    candidates = [
        path
        for base in (
            StorageLayout(
                root
            ).runs_root,
            root / "runs",
        )
        if base.is_dir()
        for path in base.rglob("summary.json")
    ]
    if not candidates:
        raise FileNotFoundError(
            "No completed run was found; pass a run directory/report or use --run with a pipeline."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


@app.command("diagnose")
def diagnose_command(
    target: Annotated[Path | None, typer.Argument(help="Run directory, summary JSON, or pipeline")] = None,
    run_pipeline: Annotated[bool, typer.Option("--run", help="Execute the 2.x Pipeline before diagnosis")] = False,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Diagnose measured bottlenecks, queue pressure, copies, fallbacks, and thermals."""
    try:
        if target is None:
            report_path = _latest_run_report(Path.cwd())
            report = json.loads(report_path.read_text(encoding="utf-8"))
        else:
            resolved = target.expanduser().resolve()
            if resolved.is_dir():
                report_path = resolved / "summary.json"
                report = json.loads(report_path.read_text(encoding="utf-8"))
            elif resolved.suffix.lower() in {".yaml", ".yml"}:
                if not run_pipeline:
                    raise ValueError(
                        "Diagnosing a pipeline requires measurements; add --run or pass a completed run."
                    )
                runtime = _runtime(resolved)
                report = (
                    runtime.run_sync()
                    if isinstance(runtime, HybridPipelineRuntime)
                    else asyncio.run(runtime.run())
                )
            else:
                report = json.loads(resolved.read_text(encoding="utf-8"))
        result = diagnose_report(report)
    except Exception as exc:
        console.print(f"[red]Diagnosis failed:[/red] {exc}")
        raise typer.Exit(1)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        console.print(f"[green]Written[/green] {output.resolve()}")
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False))
        return
    table = Table("Severity", "Code", "Target", "Finding", "Evidence")
    for finding in result["findings"]:
        table.add_row(
            str(finding["severity"]),
            str(finding["code"]),
            str(finding["target"]),
            str(finding["message"]),
            json.dumps(finding.get("evidence"), ensure_ascii=False, default=str),
        )
    console.print(table)
    if not result["findings"]:
        console.print("[green]No measured bottleneck or pressure finding.[/green]")


@app.command("explain")
def explain_command(
    target: Annotated[list[str], typer.Argument(help="Node, dotted config path, backend, or edge SOURCE:TARGET")],
    pipeline: Annotated[Path, typer.Option("--pipeline", "-p", exists=True, readable=True)] = Path("pipeline.yaml"),
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    set_values: Annotated[list[str] | None, typer.Option("--set")] = None,
    block_values: Annotated[list[str] | None, typer.Option("--block")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Explain a resolved value, node, edge, or backend selection."""
    rendered_target = " ".join(target)
    try:
        details = load_manifest_details(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        runtime = _runtime(
            pipeline,
            profile=profile,
            overrides=set_values,
            block_overrides=block_values,
        )
        result = explain_target(details, runtime.describe(), rendered_target)
    except Exception as exc:
        console.print(f"[red]Cannot explain {rendered_target!r}:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        return
    console.print(f"Target: [bold]{result.get('target')}[/bold]")
    console.print(
        "Value: "
        + yaml.safe_dump(result.get("value", result.get("selected")), sort_keys=False).strip()
    )
    console.print(f"Source: {result.get('source', result.get('evidence', '-'))}")
    console.print(f"Reason: {result.get('reason', '-')}")
    rejected = result.get("rejected") or []
    if rejected:
        console.print("Rejected: " + json.dumps(rejected, ensure_ascii=False, default=str))


@app.command("optimize")
def optimize_command(
    pipeline: Annotated[Path, typer.Argument(exists=True, readable=True)] = Path("pipeline.yaml"),
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")] = Path(".nodrix/optimization"),
    max_variants: Annotated[int, typer.Option("--max-variants", min=1, max=100)] = 12,
    latency_p95_ms: Annotated[float | None, typer.Option("--latency-p95-ms", min=0.0)] = None,
    temperature_c: Annotated[float | None, typer.Option("--temperature-c", min=0.0)] = None,
    memory_mb: Annotated[float | None, typer.Option("--memory-mb", min=0.0)] = None,
    run_benchmarks: Annotated[bool, typer.Option("--benchmark", help="Evaluate generated variants now")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate separate tuning variants; never modify the production pipeline."""
    try:
        details = load_manifest_details(pipeline)
        constraints = {
            key: value
            for key, value in {
                "latency_p95_ms": latency_p95_ms,
                "temperature_c": temperature_c,
                "memory_mb": memory_mb,
            }.items()
            if value is not None
        }
        plan = build_optimization_plan(
            pipeline,
            details.manifest,
            max_variants=max_variants,
            constraints=constraints,
        )

        outcome = execute_optimization_operation(
            plan,
            run_benchmarks=run_benchmarks,
            run_callable=_execute_benchmark_run,
            output_dir=output_dir,
        )

        if not outcome.successful:
            message = (
                outcome.execution.details.get(
                    "benchmark_error"
                )
                or outcome.execution.details.get(
                    "message"
                )
                or "optimization execution failed"
            )
            raise RuntimeError(
                str(message)
            )

        result = outcome.summary()
        spec_path = outcome.spec_path
        report_path = outcome.report_path
    except Exception as exc:
        console.print(f"[red]Optimization planning failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False, default=str))
        return
    console.print(f"[green]Generated[/green] {len(result['variants'])} variants")
    console.print(f"Benchmark spec: {spec_path}")
    console.print(f"Decision report: {report_path}")
    if result.get("recommendation"):
        console.print(
            "Recommended measured variant: "
            f"{result['recommendation'].get('selected') or 'none'}"
        )
    console.print("Source pipeline was not modified.")

@app.command("view")
def view(
    source: Annotated[str, typer.Argument(help="Stream name, nodrix:// URI, RTSP/HTTP URL, camera, or video path")],
    fps: Annotated[float, typer.Option("--fps", min=0.0)] = 0.0,
    overlay: Annotated[bool, typer.Option("--overlay/--no-overlay")] = True,
    fullscreen: Annotated[bool, typer.Option("--fullscreen")] = False,
    scale: Annotated[float, typer.Option("--scale", min=0.05, max=8.0)] = 1.0,
    decoder: Annotated[str, typer.Option("--decoder", help="auto, opencv, or ffmpeg")] = "auto",
    rtsp_transport: Annotated[str, typer.Option("--rtsp-transport", help="tcp or udp")] = "tcp",
    headless: Annotated[bool, typer.Option("--headless")] = False,
    max_frames: Annotated[int, typer.Option("--max-frames", min=0)] = 0,
) -> None:
    """Open the low-latency Plyctl Viewer."""
    from .viewer import ViewerError, run_viewer

    try:
        report = run_viewer(
            source,
            max_fps=fps,
            overlay=overlay,
            fullscreen=fullscreen,
            scale=scale,
            decoder=decoder,
            rtsp_transport=rtsp_transport,
            headless=headless,
            max_frames=max_frames,
        )
    except (ViewerError, OSError, LookupError, ValueError) as exc:
        console.print(f"[red]Viewer failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(
        f"Displayed {report['displayed']} frames at {report['display_fps']:.1f} FPS; "
        f"overwritten={report['overwritten']}"
    )


@media_app.command("doctor")
def media_doctor_command(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check FFmpeg/FFprobe and available software/hardware encoders."""
    from .media import MediaError, media_doctor

    try:
        report = media_doctor()
    except MediaError as exc:
        console.print(f"[red]Media doctor failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(report))
        return
    console.print(report["ffmpeg"])
    table = Table("Encoder", "Available")
    for name, available in report["encoders"].items():
        table.add_row(name, "yes" if available else "no")
    console.print(table)


@media_app.command("select-encoder")
def media_select_encoder_command(
    codec: Annotated[str, typer.Argument(help="h264 or h265")] = "h264",
    requested: Annotated[str, typer.Option("--encoder", help="auto or an explicit FFmpeg encoder")] = "auto",
    acceleration: Annotated[str, typer.Option("--acceleration", help="required, preferred, or disabled")] = "required",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Probe encoder backends using an explicit hardware policy."""
    from .media import select_encoder

    try:
        result = select_encoder(codec, requested, acceleration)
    except Exception as exc:
        console.print(f"[red]Encoder selection failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(result))
        return
    selected = result.get("selected") or "none"
    style = "green" if result.get("hardware") else "yellow"
    console.print(f"Selected: [{style}]{selected}[/{style}]")
    console.print(f"Policy: {result.get('acceleration')}")
    console.print(f"Hardware: {'yes' if result.get('hardware') else 'no'}")
    console.print(f"Reason: {result.get('reason')}")
    for attempt in result.get("attempts", []):
        marker = "✓" if attempt.get("ok") else "×"
        console.print(f"  {marker} {attempt.get('encoder')}: {attempt.get('reason')}")
    if not result.get("ok"):
        raise typer.Exit(1)


@media_app.command("probe")
def media_probe_command(
    source: Annotated[str, typer.Argument(help="File, RTSP/HTTP/SRT URL, or FFmpeg input")],
    input_format: Annotated[str | None, typer.Option("--format", help="Optional FFmpeg input format")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect media streams with ffprobe."""
    from .media import MediaError, probe_media

    try:
        report = probe_media(source, input_format=input_format)
    except MediaError as exc:
        console.print(f"[red]Probe failed:[/red] {exc}")
        raise typer.Exit(1)
    if json_output:
        console.print_json(json.dumps(report))
        return
    video = report.get("video") or {}
    audio = report.get("audio") or {}
    table = Table("Kind", "Codec", "Details")
    if video:
        table.add_row("video", str(video.get("codec")), f"{video.get('width')}x{video.get('height')} @ {video.get('fps', 0):.3f} FPS")
    if audio:
        table.add_row("audio", str(audio.get("codec")), f"{audio.get('sample_rate')} Hz, {audio.get('channels')} ch")
    console.print(table)


@media_app.command("record")
def media_record_command(
    source: Annotated[str, typer.Argument(help="Input URL or file")],
    output: Annotated[str, typer.Argument(help="Output media file")],
    copy: Annotated[bool, typer.Option("--copy/--transcode", help="Copy encoded packets when possible")] = True,
    codec: Annotated[str, typer.Option("--codec", help="h264 or h265 when transcoding")] = "h264",
    encoder: Annotated[str | None, typer.Option("--encoder", help="Explicit FFmpeg encoder name")] = None,
    duration: Annotated[float, typer.Option("--duration", min=0.0)] = 0.0,
    rtsp_transport: Annotated[str, typer.Option("--rtsp-transport")] = "tcp",
) -> None:
    """Record a media source with stream copy or low-latency transcoding."""
    from .media import run_ffmpeg_relay

    code = run_ffmpeg_relay(source, output, copy=copy, codec=codec, encoder=encoder, duration=duration, rtsp_transport=rtsp_transport)
    if code != 0:
        raise typer.Exit(code)
    console.print(f"[green]Recorded[/green] {output}")


@media_app.command("relay")
def media_relay_command(
    source: Annotated[str, typer.Argument(help="Input URL or file")],
    output: Annotated[str, typer.Argument(help="RTSP/SRT/UDP URL or file")],
    copy: Annotated[bool, typer.Option("--copy/--transcode")] = True,
    codec: Annotated[str, typer.Option("--codec")] = "h264",
    encoder: Annotated[str | None, typer.Option("--encoder")] = None,
    rtsp_transport: Annotated[str, typer.Option("--rtsp-transport")] = "tcp",
) -> None:
    """Relay media directly through FFmpeg without entering the Python frame path."""
    from .media import run_ffmpeg_relay

    code = run_ffmpeg_relay(source, output, copy=copy, codec=codec, encoder=encoder, rtsp_transport=rtsp_transport)
    raise typer.Exit(code)
