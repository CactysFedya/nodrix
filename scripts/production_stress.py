from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile

from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.manifest import PipelineManifest
from nodrix.registry import BUILTINS
from nodrix.builtin_nodes import SyntheticSource, IdentityNode, CounterSink


def main(repeats: int = 50, messages: int = 1000) -> None:
    BUILTINS.update({
        "stress.source": SyntheticSource,
        "stress.identity": IdentityNode,
        "stress.sink": CounterSink,
    })
    manifest = PipelineManifest.model_validate({
        "metadata": {"name": "production-stress"},
        "runtime": {"metrics": {"enabled": False}},
        "nodes": {
            "source": {"uses": "stress.source", "parameters": {"count": messages}},
            "identity": {"uses": "stress.identity"},
            "sink": {"uses": "stress.sink"},
        },
        "edges": [
            {"from": "source.output", "to": "identity.input", "queue": {"capacity": 1024, "policy": "block"}},
            {"from": "identity.output", "to": "sink.input", "queue": {"capacity": 1024, "policy": "block"}},
        ],
    })
    with tempfile.TemporaryDirectory(prefix="nodrix-stress-") as tmp:
        root = Path(tmp)
        path = root / "pipeline.yaml"
        path.write_text("metadata: {name: production-stress}\nnodes: {}\nedges: []\n", encoding="utf-8")
        for index in range(repeats):
            runtime = HybridPipelineRuntime(manifest, path, run_root=root / "runs")
            runtime.build()
            report = runtime.run_sync()
            if report["status"] != "completed" or report["nodes"]["sink"]["messages"] != messages:
                raise RuntimeError(f"stress run failed at iteration {index}")
    print({"runs": repeats, "messages_per_run": messages, "status": "ok"})


if __name__ == "__main__":
    main()
