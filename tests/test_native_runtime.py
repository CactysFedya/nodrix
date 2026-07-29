from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from nodrix.manifest import load_manifest
from nodrix.native_runtime import NativePipelineRuntime


def test_native_manifest_builds() -> None:
    root = Path(__file__).resolve().parents[1]
    pipeline = root / "examples" / "native_high_performance.yaml"
    runtime = NativePipelineRuntime(load_manifest(pipeline), pipeline)
    runtime.build()
    description = runtime.describe()
    assert description["engine"] == "native"
    assert description["nodes"]["stage_a"]["inputs"] == {"input": "core.any"}
    assert len(description["edges"]) == 3


@pytest.mark.skipif(
    os.environ.get("NODRIX_NATIVE_E2E") != "1",
    reason="set NODRIX_NATIVE_E2E=1 to compile and execute the native runner",
)
def test_native_runtime_executes_end_to_end(tmp_path: Path) -> None:
    if shutil.which("cmake") is None or shutil.which("c++") is None:
        pytest.skip("CMake and a C++ compiler are required")

    pipeline = tmp_path / "native-e2e.yaml"
    pipeline.write_text(
        """apiVersion: nodrix.dev/v1
kind: Pipeline
metadata:
  name: native-e2e
runtime:
  mode: offline
  engine: native
nodes:
  source:
    uses: native.synthetic_source
    parameters:
      count: 4096
      payload_bytes: 4096
      reuse_buffer: true
  stage:
    uses: native.identity
  sink:
    uses: native.counter_sink
edges:
  - from: source.output
    to: stage.input
    queue:
      capacity: 64
      policy: block
  - from: stage.output
    to: sink.input
    queue:
      capacity: 64
      policy: block
""",
        encoding="utf-8",
    )

    runtime = NativePipelineRuntime(
        load_manifest(pipeline),
        pipeline,
        run_root=tmp_path / "runs",
    )
    runtime.toolchain.build_dir = tmp_path / "native-build"

    report = asyncio.run(runtime.run())

    version = subprocess.run(
        [report["native_runner"], "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert version.stdout.strip() == "nodrix-native-runner 1.7.0"
    assert report["engine"] == "native-cpp20"
    assert report["status"] == "completed"
    assert report["nodes"]["stage"]["messages"] == 4096
    assert report["nodes"]["sink"]["messages"] == 4096
    assert report["nodes"]["stage"]["errors"] == 0
    assert report["nodes"]["sink"]["errors"] == 0
    assert all(edge["dropped"] == 0 for edge in report["edges"])
    assert (Path(report["run_dir"]) / "native-run.json").is_file()
