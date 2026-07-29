from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

import nodrix
from nodrix import Message
from nodrix.execution_plan import (
    EXECUTION_PLAN_SCHEMA,
    compile_execution_plan,
    validate_execution_plan,
)
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.manifest import load_manifest
from nodrix.native_runtime import NativePipelineRuntime


def _write_pipeline(path: Path, *, token: str | None = None) -> Path:
    raw: dict[str, object] = {
        "apiVersion": "nodrix.dev/v1",
        "kind": "Pipeline",
        "metadata": {"name": "v160"},
        "runtime": {"engine": "unified"},
        "nodes": {
            "source": {
                "uses": "core.synthetic_source",
                "parameters": {"count": 1},
            },
            "sink": {"uses": "core.counter_sink"},
        },
        "edges": [{"from": "source.output", "to": "sink.input"}],
    }
    if token:
        raw["streams"] = {
            "exports": [
                {
                    "name": "/secure",
                    "from": "source.output",
                    "access": {"mode": "token", "token": token},
                }
            ]
        }
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_v160_version() -> None:
    assert nodrix.__version__ == "1.8.0"


def test_execution_plan_is_deterministic_and_secret_free(tmp_path: Path) -> None:
    pipeline = _write_pipeline(tmp_path / "pipeline.yaml", token="never-write-this")
    manifest = load_manifest(pipeline)
    runtime = HybridPipelineRuntime(manifest, pipeline)
    first = compile_execution_plan(manifest, runtime.describe())
    second = compile_execution_plan(manifest, runtime.describe())

    assert first == second
    assert first["schema"] == EXECUTION_PLAN_SCHEMA
    assert first["topological_order"] == ["source", "sink"]
    assert first["summary"]["nodes"] == 2
    assert first["resolved_manifest"]["streams"]["exports"][0]["access"]["token"] == "***REDACTED***"
    assert "never-write-this" not in str(first)
    validate_execution_plan(first)


def test_c_abi_header_is_valid_c11(tmp_path: Path) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("a C compiler is required")
    root = Path(__file__).parents[1]
    source = tmp_path / "abi.c"
    source.write_text(
        '#include "nodrix/c_api.h"\n'
        "_Static_assert(NODRIX_C_ABI_VERSION == 0x00020000u, \"ABI\");\n"
        "int main(void) { nodrix_node_api_v2 api = {0}; return (int)api.struct_size; }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-fsyntax-only",
            f"-I{root / 'src/nodrix/native/include'}",
            str(source),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_standalone_native_runner_rejects_external_plugin_path(tmp_path: Path) -> None:
    pipeline = _write_pipeline(tmp_path / "pipeline.yaml")
    raw = yaml.safe_load(pipeline.read_text(encoding="utf-8"))
    raw["runtime"]["engine"] = "native"
    raw["nodes"] = {
        "source": {
            "uses": "native:./plugin.so#demo.source",
            "outputs": {"output": "core.object"},
        }
    }
    raw["edges"] = []
    pipeline.write_text(yaml.safe_dump(raw), encoding="utf-8")
    runtime = NativePipelineRuntime(load_manifest(pipeline), pipeline)
    with pytest.raises(Exception, match="engine: unified"):
        runtime.build()


@pytest.mark.skipif(
    os.environ.get("NODRIX_NATIVE_E2E") != "1",
    reason="set NODRIX_NATIVE_E2E=1 to compile the C ABI example",
)
def test_c_abi_plugin_zero_copy_roundtrip(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("a C++ compiler is required")
    root = Path(__file__).parents[1]
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    library = tmp_path / f"libfilter{suffix}"
    command = [
        compiler,
        "-std=c++20",
        "-O2",
        "-fPIC",
        "-shared",
        f"-I{root / 'src/nodrix/native/include'}",
        str(root / "src/nodrix/native/examples/filter_plugin.cpp"),
        "-o",
        str(library),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr

    from nodrix._native_plugin import NativeNodeHost

    host = NativeNodeHost(str(library), "demo.frame_passthrough", "{}")
    payload = bytearray(b"NDRX")
    output = host.process(
        {"frame": Message("vision.frame", payload, sequence=7)}
    )["frame"]
    payload[0] = ord("X")
    assert bytes(memoryview(output.payload)) == b"XDRX"
