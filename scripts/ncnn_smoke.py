#!/usr/bin/env python3
"""Run one real NCNN inference through the official Plugin C ABI provider."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--param", type=Path, required=True)
    parser.add_argument("--bin", dest="binary", type=Path, required=True)
    parser.add_argument("--size", type=int, default=227)
    parser.add_argument("--input-blob", default="data")
    parser.add_argument("--output-blob", default="prob")
    parser.add_argument("--num-classes", type=int, default=996)
    parser.add_argument("--iterations", type=int, default=25)
    args = parser.parse_args()

    for path in (args.plugin, args.param, args.binary):
        if not path.is_file():
            raise FileNotFoundError(path)
    os.environ["NODRIX_NCNN_PLUGIN"] = str(args.plugin.resolve())

    import numpy as np

    from nodrix import Message
    from nodrix.cv_types import Frame
    from nodrix.node import NodeContext
    from nodrix.vision.nodes import NativeNcnnDetectorNode

    root = Path(tempfile.mkdtemp(prefix="nodrix-ncnn-smoke-"))
    node = NativeNcnnDetectorNode(
        {
            "param": str(args.param.resolve()),
            "bin": str(args.binary.resolve()),
            "imgsz": args.size,
            "input_blob": args.input_blob,
            "output_blob": args.output_blob,
            # SqueezeNet produces 1000 class scores. Treating four values as
            # box coordinates exercises the common 4+C decoder and yields an
            # empty result at conf=1 without claiming detector semantics.
            "output_format": "ultralytics",
            "num_classes": args.num_classes,
            "conf": 1.0,
        }
    )
    node.open(
        NodeContext(
            name="detector",
            run_dir=root / "run",
            project_dir=root,
            runtime_mode="offline",
        )
    )
    print("Native NCNN model opened", flush=True)
    try:
        frame = Frame.from_numpy(
            np.zeros(
                (args.size, args.size, 3),
                dtype=np.uint8,
            )
        )
        message = Message(
            type="vision.frame",
            payload=frame,
        )
        for _ in range(max(1, args.iterations)):
            outputs = node.process({"frame": message})
            if outputs is None:
                raise RuntimeError(
                    "native NCNN provider emitted no output"
                )
            detections = outputs["detections"].payload
            if detections.attributes.get("backend") != "ncnn-cpp":
                raise RuntimeError("unexpected NCNN backend metadata")
            if detections.boxes.shape != (0, 4):
                raise RuntimeError(
                    "unexpected smoke output shape: "
                    f"{detections.boxes.shape}"
                )
        print(
            f"Native NCNN inference passed ({max(1, args.iterations)} iterations)",
            flush=True,
        )
    finally:
        node.close()
        print("Native NCNN node closed", flush=True)

    print("Native NCNN compile/link/load/inference smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
