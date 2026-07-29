from __future__ import annotations

import time
import numpy as np

from nodrix import Message, Node, SourceNode
from nodrix.vision import Detections, Frame, Tracks


class SyntheticFrameSource(SourceNode):
    output_types = {"frame": "vision.frame"}

    def produce(self):
        count = int(self.parameters.get("count", 30))
        width = int(self.parameters.get("width", 640))
        height = int(self.parameters.get("height", 360))
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        typed = Frame.from_numpy(frame)
        for sequence in range(count):
            yield {"frame": Message(
                type="vision.frame", payload=typed, sequence=sequence,
                timestamp_ns=time.time_ns(), trace_id=sequence,
            )}


class DemoDetector(Node):
    input_types = {"frame": "vision.frame"}
    output_types = {"detections": "vision.detections"}

    def process(self, inputs):
        frame = inputs["frame"]
        seq = frame.sequence
        detections = Detections(
            boxes=[[10 + seq, 20, 80 + seq, 120]],
            class_ids=[0],
            scores=[0.90],
        )
        return {"detections": Message(
            type="vision.detections", payload=detections,
            sequence=seq, timestamp_ns=frame.timestamp_ns,
            trace_id=frame.trace_id, created_ns=frame.created_ns,
        )}


class DemoTracker(Node):
    input_types = {"detections": "vision.detections"}
    output_types = {"tracks": "vision.tracks"}

    def process(self, inputs):
        source = inputs["detections"]
        detections = source.payload
        tracks = Tracks(
            boxes=detections.boxes,
            track_ids=np.arange(1, len(detections) + 1),
            scores=detections.scores,
            class_ids=detections.class_ids,
        )
        return {"tracks": source.with_updates(type="vision.tracks", payload=tracks)}


class TrackFilter(Node):
    input_types = {"tracks": "vision.tracks"}
    output_types = {"tracks": "vision.tracks"}

    def process(self, inputs):
        source = inputs["tracks"]
        tracks = source.payload
        keep = tracks.scores >= float(self.parameters.get("confidence", 0.5))
        filtered = Tracks(
            boxes=tracks.boxes[keep], track_ids=tracks.track_ids[keep],
            scores=tracks.scores[keep], class_ids=tracks.class_ids[keep],
        )
        return {"tracks": source.with_updates(payload=filtered)}


class DemoReID(Node):
    input_types = {"tracks": "vision.tracks"}
    output_types = {"identified_tracks": "vision.identified_tracks"}

    def process(self, inputs):
        source = inputs["tracks"]
        tracks = source.payload
        identified = Tracks(
            boxes=tracks.boxes, track_ids=tracks.track_ids,
            scores=tracks.scores, class_ids=tracks.class_ids,
            attributes={"global_object_ids": np.full(len(tracks), 1001, dtype=np.int64)},
        )
        return {"identified_tracks": source.with_updates(
            type="vision.identified_tracks", payload=identified,
        )}
