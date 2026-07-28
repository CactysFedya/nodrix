import asyncio
from pathlib import Path

from nodrix.manifest import load_manifest
from nodrix.runtime import PipelineRuntime


def test_quickstart_runtime(tmp_path):
    path = Path(__file__).parents[1] / "examples" / "quickstart" / "pipeline.yaml"
    runtime = PipelineRuntime(load_manifest(path), path, run_root=tmp_path)
    runtime.build()
    report = asyncio.run(runtime.run())
    assert report["status"] == "completed"
    assert report["nodes"]["source"]["messages"] == 5
    assert report["nodes"]["delay"]["messages"] == 5
    assert report["nodes"]["writer"]["messages"] == 5
    run_dir = Path(report["run_dir"])
    assert (run_dir / "messages.jsonl").exists()
    assert (run_dir / "run.json").exists()
