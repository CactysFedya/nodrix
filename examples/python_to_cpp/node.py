from __future__ import annotations

from nodrix import Node, Message

try:
    from _frame_mean_native import frame_mean
    BACKEND = "cpp"
except ImportError:
    from python_backend import frame_mean
    BACKEND = "python"


class FrameMeanNode(Node):
    input_types = {"frame": "vision.frame"}
    output_types = {"mean": "core.number"}

    def process(self, inputs):
        source = inputs["frame"]
        return {
            "mean": Message(
                type="core.number",
                payload=frame_mean(source.payload),
                sequence=source.sequence,
                timestamp_ns=source.timestamp_ns,
                trace_id=source.trace_id,
                metadata={"backend": BACKEND},
            )
        }
