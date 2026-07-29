from __future__ import annotations

import numpy as np

from nodrix import SourceNode, Message


class ArraySource(SourceNode):
    output_types = {"frame": "vision.frame"}

    def produce(self):
        count = int(self.parameters.get("count", 100))
        shape = tuple(self.parameters.get("shape", [360, 640, 3]))
        frame = np.arange(np.prod(shape), dtype=np.uint8).reshape(shape)
        for sequence in range(count):
            yield {
                "frame": Message(
                    type="vision.frame",
                    payload=frame,
                    sequence=sequence,
                    trace_id=sequence,
                    metadata={"shape": list(shape)},
                )
            }
