import asyncio
from pathlib import Path

from nodrix.manifest import load_manifest
from nodrix.runtime import PipelineRuntime


def test_custom_cv_nodes(tmp_path):
    path = Path(__file__).parents[1] / "examples" / "cv_demo" / "pipeline.yaml"
    runtime = PipelineRuntime(load_manifest(path), path, run_root=tmp_path)
    runtime.build()
    report = asyncio.run(runtime.run())
    assert report["status"] == "completed"
    assert report["nodes"]["reid"]["messages"] > 0
    assert Path(report["run_dir"], "identified_tracks.jsonl").exists()
