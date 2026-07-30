from __future__ import annotations

import asyncio
import gc
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest
import yaml

from nodrix.errors import RuntimeGraphError
from nodrix.manifest import load_manifest
from nodrix.messages import Message
from nodrix.native_runtime import NativePipelineRuntime


def _library_name(stem: str) -> str:
    if os.name == "nt":
        return f"{stem}.dll"
    if sys.platform == "darwin":
        return f"lib{stem}.dylib"
    return f"lib{stem}.so"


@pytest.fixture(scope="module")
def native_artifacts(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, Path, Path]:
    if shutil.which("cmake") is None or shutil.which("c++") is None:
        pytest.skip("CMake and a C++ compiler are required")
    root = Path(__file__).resolve().parents[1]
    build = tmp_path_factory.mktemp("native-plugin-build")
    subprocess.run(
        [
            "cmake",
            "-S",
            str(root / "src/nodrix/native"),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DNODRIX_BUILD_EXAMPLE_PLUGIN=ON",
            "-DNODRIX_BUILD_TESTS=ON",
            "-DNODRIX_NATIVE_LTO=OFF",
            "-DNODRIX_NATIVE_MARCH_NATIVE=OFF",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "cmake",
            "--build",
            str(build),
            "--config",
            "Release",
            "--target",
            "nodrix-native-runner",
            "nodrix_conformance_plugin",
            "nodrix_test_abi_mismatch",
            "nodrix_test_missing_symbol",
            "--parallel",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    runner_name = (
        "nodrix-native-runner.exe"
        if os.name == "nt"
        else "nodrix-native-runner"
    )
    runners = list(build.rglob(runner_name))
    libraries = list(
        build.rglob(_library_name("nodrix_conformance_plugin"))
    )
    abi_mismatch = list(
        build.rglob(_library_name("nodrix_test_abi_mismatch"))
    )
    missing_symbol = list(
        build.rglob(_library_name("nodrix_test_missing_symbol"))
    )
    assert runners, "native runner was not built"
    assert libraries, "conformance plugin was not built"
    assert abi_mismatch, "ABI mismatch fixture was not built"
    assert missing_symbol, "missing symbol fixture was not built"
    return (
        runners[0],
        libraries[0],
        abi_mismatch[0],
        missing_symbol[0],
    )


def _pipeline(plugin: Path, *, count: int = 100_000) -> dict:
    reference = f"native:{plugin}"
    return {
        "apiVersion": "nodrix.dev/v2",
        "kind": "Pipeline",
        "metadata": {"name": "external-native-conformance"},
        "runtime": {
            "engine": "native",
            "shutdown": {"timeout_ms": 5000},
            "metrics": {"interval_ms": 100},
        },
        "nodes": {
            "source": {
                "uses": f"{reference}#conformance.source",
                "parameters": {"count": count},
                "health": {"timeout_ms": 5000},
            },
            "bridge_a": {
                "uses": f"{reference}#conformance.bridge",
                "health": {"timeout_ms": 5000},
            },
            "bridge_b": {
                "uses": f"{reference}#conformance.bridge",
                "health": {"timeout_ms": 5000},
            },
            "sink": {
                "uses": f"{reference}#conformance.sink",
                "parameters": {"count": count},
                "health": {"timeout_ms": 5000},
            },
        },
        "fragments": {},
        "edges": [
            {
                "from": "source.output",
                "to": "bridge_a.input",
                "queue": {"capacity": 64, "policy": "block"},
            },
            {
                "from": "bridge_a.output",
                "to": "bridge_b.input",
                "queue": {"capacity": 64, "policy": "block"},
            },
            {
                "from": "bridge_b.output",
                "to": "sink.input",
                "queue": {"capacity": 64, "policy": "block"},
            },
        ],
        "streams": {},
        "recording": {},
        "security": {},
        "placement": {},
    }


def _write_pipeline(path: Path, document: dict) -> Path:
    path.write_text(
        yaml.safe_dump(document, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_external_plugin_source_processor_sink_and_correlation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_artifacts: tuple[Path, Path, Path, Path],
) -> None:
    runner, plugin, _, _ = native_artifacts
    monkeypatch.setenv("NODRIX_NATIVE_RUNNER", str(runner))
    pipeline = _write_pipeline(
        tmp_path / "pipeline.yaml",
        _pipeline(plugin),
    )
    runtime = NativePipelineRuntime(
        load_manifest(pipeline),
        pipeline,
        run_root=tmp_path / "runs",
    )
    report = asyncio.run(runtime.run())

    assert report["status"] == "completed"
    assert report["nodes"]["bridge_a"]["messages"] == 100_000
    assert report["nodes"]["bridge_b"]["messages"] == 100_000
    assert report["nodes"]["sink"]["messages"] == 100_000
    assert all(node["state"] == "STOPPED" for node in report["nodes"].values())
    assert all(node["errors"] == 0 for node in report["nodes"].values())
    assert all(edge["dropped"] == 0 for edge in report["edges"])
    run_dir = Path(report["run_dir"])
    assert (run_dir / "status.json").is_file()
    events = (run_dir / "native-events.jsonl").read_text(encoding="utf-8")
    assert '"state":"RUNNING"' in events
    assert '"state":"STOPPED"' in events


@pytest.mark.parametrize(
    "policy",
    [
        "exact_sequence",
        "approximate_timestamp",
        "latest_available",
        "zip",
    ],
)
def test_native_synchronization_policies_accept_absent_optional_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_artifacts: tuple[Path, Path, Path, Path],
    policy: str,
) -> None:
    runner, plugin, _, _ = native_artifacts
    monkeypatch.setenv("NODRIX_NATIVE_RUNNER", str(runner))
    count = 1000
    document = _pipeline(plugin, count=count)
    document["metadata"]["name"] = f"optional-{policy}"
    document["nodes"] = {
        "source": {
            "uses": f"native:{plugin}#conformance.source",
            "parameters": {"count": count},
            "health": {"timeout_ms": 5000},
        },
        "sink": {
            "uses": f"native:{plugin}#conformance.optional_sink",
            "parameters": {"count": count},
            "synchronization": {
                "policy": policy,
                "trigger_port": (
                    "input" if policy == "latest_available" else None
                ),
            },
            "health": {"timeout_ms": 5000},
        },
    }
    document["edges"] = [
        {
            "from": "source.output",
            "to": "sink.input",
            "queue": {"capacity": 16, "policy": "block"},
        }
    ]
    pipeline = _write_pipeline(
        tmp_path / f"{policy}.yaml",
        document,
    )
    runtime = NativePipelineRuntime(
        load_manifest(pipeline),
        pipeline,
        run_root=tmp_path / "runs",
    )
    report = asyncio.run(runtime.run())
    assert report["nodes"]["sink"]["messages"] == count
    assert report["nodes"]["sink"]["errors"] == 0


@pytest.mark.parametrize("trace_id", ["trace:string/0001", 2**63 + 17])
def test_python_plugin_plugin_python_preserves_message_context(
    native_artifacts: tuple[Path, Path, Path, Path],
    trace_id: str | int,
) -> None:
    _, plugin, _, _ = native_artifacts
    try:
        from nodrix._native_plugin import NativeNodeHost
    except ImportError:
        pytest.skip("Plugin C ABI host extension is not built")
    first = NativeNodeHost(
        str(plugin),
        "conformance.bridge",
        "{}",
    )
    second = NativeNodeHost(
        str(plugin),
        "conformance.bridge",
        "{}",
    )
    payload = bytearray([9] * 64)
    original = Message(
        "core.bytes",
        payload,
        sequence=9,
        timestamp_ns=1900,
        pipeline_id="pipeline/тест",
        run_id="run-0001",
        source_id="camera.front",
        stream_id="/frames/main",
        trace_id=trace_id,
        span_id="span:fedcba9876543210",
    )
    if isinstance(trace_id, str):
        original.trace_id = "trace:0123456789abcdef"
    first_output = first.process({"input": original})["output"]
    output = second.process({"input": first_output})["output"]
    payload[0] = 9

    assert output.sequence == original.sequence
    assert output.timestamp_ns == original.timestamp_ns
    assert output.pipeline_id == original.pipeline_id
    assert output.run_id == original.run_id
    assert output.source_id == original.source_id
    assert output.stream_id == original.stream_id
    assert output.trace_id == original.trace_id
    assert output.span_id == original.span_id
    assert bytes(memoryview(output.payload)) == bytes(payload)


def test_plugin_owned_output_keeps_library_loaded(
    native_artifacts: tuple[Path, Path, Path, Path],
) -> None:
    _, plugin, _, _ = native_artifacts
    try:
        from nodrix._native_plugin import NativeNodeHost
    except ImportError:
        pytest.skip("Plugin C ABI host extension is not built")
    source = NativeNodeHost(
        str(plugin),
        "conformance.source",
        '{"count":1}',
    )
    output = source.process({})["output"]
    del source
    gc.collect()
    assert bytes(memoryview(output.payload)) == bytes([0] * 64)
    del output
    gc.collect()


def test_external_plugin_error_reaches_run_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_artifacts: tuple[Path, Path, Path, Path],
) -> None:
    runner, plugin, _, _ = native_artifacts
    monkeypatch.setenv("NODRIX_NATIVE_RUNNER", str(runner))
    document = _pipeline(plugin, count=1)
    document["nodes"] = {
        "source": {
            "uses": "native.synthetic_source",
            "parameters": {"count": 1},
            "health": {"timeout_ms": 5000},
        },
        "failure": {
            "uses": f"native:{plugin}#conformance.error",
            "health": {"timeout_ms": 5000},
        },
    }
    document["edges"] = [
        {
            "from": "source.output",
            "to": "failure.input",
            "queue": {"capacity": 2, "policy": "block"},
        }
    ]
    pipeline = _write_pipeline(tmp_path / "error.yaml", document)
    runtime = NativePipelineRuntime(
        load_manifest(pipeline),
        pipeline,
        run_root=tmp_path / "runs",
    )
    with pytest.raises(
        RuntimeGraphError,
        match="intentional conformance plugin failure",
    ):
        asyncio.run(runtime.run())
    reports = list((tmp_path / "runs").glob("*/native-run.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    failure = report["nodes"]["failure"]
    assert failure["state"] == "FAILED"
    assert "intentional conformance plugin failure" in failure["last_error"]


@pytest.mark.parametrize(
    ("artifact_index", "expected"),
    [
        (2, "version mismatch"),
        (3, "Missing Plugin C ABI 2.0 symbol"),
    ],
)
def test_native_runner_rejects_incompatible_plugin_before_open(
    tmp_path: Path,
    native_artifacts: tuple[Path, Path, Path, Path],
    artifact_index: int,
    expected: str,
) -> None:
    runner = native_artifacts[0]
    plugin = native_artifacts[artifact_index]

    def encoded(value: str) -> str:
        return value.encode("utf-8").hex()

    run_dir = tmp_path / f"bad-{artifact_index}"
    run_dir.mkdir()
    plan = tmp_path / f"bad-{artifact_index}.vpp"
    reference = f"native:{plugin}#invalid.node"
    plan.write_text(
        "\n".join(
            [
                "NODRIX_NATIVE_PLAN_V2",
                f"PIPELINE\t{encoded('invalid-plugin')}",
                f"RUN_DIR\t{encoded(str(run_dir))}",
                "RUNTIME\t1000\t100",
                (
                    f"NODE\t{encoded('invalid')}\t"
                    f"{encoded(reference)}\t{encoded('{}')}"
                ),
                (
                    f"SYNC\t{encoded('invalid')}\t"
                    "exact_sequence\t20000000\t\t"
                ),
                "END",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(runner), "--plan", str(plan)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert expected in result.stderr
    assert not (run_dir / "native-run.json").exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="subprocess.terminate does not deliver a console control event",
)
def test_external_plugin_graceful_signal_shutdown(
    tmp_path: Path,
    native_artifacts: tuple[Path, Path, Path, Path],
) -> None:
    runner, plugin, _, _ = native_artifacts
    run_dir = tmp_path / "signal-run"
    run_dir.mkdir()

    def encoded(value: str) -> str:
        return value.encode("utf-8").hex()

    reference = f"native:{plugin}"
    plan = tmp_path / "signal.vpp"
    lines = [
        "NODRIX_NATIVE_PLAN_V2",
        f"PIPELINE\t{encoded('signal-conformance')}",
        f"RUN_DIR\t{encoded(str(run_dir))}",
        "RUNTIME\t5000\t100",
        (
            f"NODE\t{encoded('source')}\t"
            f"{encoded(reference + '#conformance.source')}\t"
            f"{encoded(json.dumps({'count': 1_000_000_000}))}"
        ),
        f"SYNC\t{encoded('source')}\texact_sequence\t20000000\t\t",
        (
            f"NODE\t{encoded('sink')}\t"
            f"{encoded(reference + '#conformance.sink')}\t"
            f"{encoded(json.dumps({'count': 0}))}"
        ),
        f"SYNC\t{encoded('sink')}\texact_sequence\t20000000\t\t",
        (
            f"EDGE\t{encoded('source')}\t{encoded('output')}\t"
            f"{encoded('sink')}\t{encoded('input')}\t8\tblock"
        ),
        "END",
    ]
    plan.write_text("\n".join(lines) + "\n", encoding="utf-8")
    process = subprocess.Popen(
        [str(runner), "--plan", str(plan)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    events = run_dir / "native-events.jsonl"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if events.is_file() and '"state":"RUNNING"' in events.read_text(
            encoding="utf-8"
        ):
            break
        time.sleep(0.01)
    else:
        process.kill()
        pytest.fail("native runner did not reach RUNNING")
    process.send_signal(signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, (stdout, stderr)
    report = json.loads(
        (run_dir / "native-run.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "completed"
    assert all(node["state"] == "STOPPED" for node in report["nodes"].values())
    assert not (run_dir / "forced-shutdown.json").exists()


@pytest.mark.skipif(
    os.environ.get("NODRIX_STRESS") != "1",
    reason="set NODRIX_STRESS=1 for the million-message retention test",
)
def test_external_plugin_million_messages_without_retained_buffers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_artifacts: tuple[Path, Path, Path, Path],
) -> None:
    runner, plugin, _, _ = native_artifacts
    monkeypatch.setenv("NODRIX_NATIVE_RUNNER", str(runner))
    pipeline = _write_pipeline(
        tmp_path / "million.yaml",
        _pipeline(plugin, count=1_000_000),
    )
    runtime = NativePipelineRuntime(
        load_manifest(pipeline),
        pipeline,
        run_root=tmp_path / "runs",
    )
    report = asyncio.run(runtime.run())
    assert report["nodes"]["sink"]["messages"] == 1_000_000
