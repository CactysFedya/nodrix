from pathlib import Path

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
