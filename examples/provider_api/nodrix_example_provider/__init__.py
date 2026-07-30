from __future__ import annotations

from typing import Any

from nodrix import Node, ProviderRuntime


class EchoNode(Node):
    input_types = {"input": "core.any"}
    output_types = {"output": "core.any"}

    def process(self, inputs):
        return {"output": inputs["input"]}


def safe_probe() -> dict[str, Any]:
    return {
        "status": "ok",
        "implementation": f"{EchoNode.__module__}:{EchoNode.__name__}",
    }


def provider() -> ProviderRuntime:
    return ProviderRuntime(
        provider_id="example.echo",
        nodes={"example.echo": EchoNode},
        probes={"example.echo.safe": safe_probe},
    )
