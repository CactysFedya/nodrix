"""Dedicated ROS graph worker started inside a sourced ROS environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import threading
import time


def _write_snapshot(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(document, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=0.2)
    args = parser.parse_args()
    stopped = threading.Event()

    def request_stop(*_args: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor

        context = Context()
        rclpy.init(args=None, context=context)
        node = rclpy.create_node("nodrix_graph_watcher", context=context)
        executor = SingleThreadedExecutor(context=context)
        executor.add_node(node)
        try:
            while not stopped.is_set():
                executor.spin_once(timeout_sec=max(float(args.interval), 0.05))
                topics: dict[str, dict] = {}
                for name, types in node.get_topic_names_and_types():
                    topics[str(name)] = {
                        "types": sorted(str(item) for item in types),
                        "publishers": int(node.count_publishers(name)),
                        "subscribers": int(node.count_subscribers(name)),
                    }
                _write_snapshot(
                    args.snapshot,
                    {
                        "schema": "nodrix.ros2-graph/v1",
                        "status": "ok",
                        "updated_ns": time.time_ns(),
                        "topics": topics,
                    },
                )
        finally:
            executor.remove_node(node)
            node.destroy_node()
            executor.shutdown(timeout_sec=1.0)
            rclpy.shutdown(context=context)
    except BaseException as exc:
        _write_snapshot(
            args.snapshot,
            {
                "schema": "nodrix.ros2-graph/v1",
                "status": "error",
                "updated_ns": time.time_ns(),
                "error": f"{type(exc).__name__}: {exc}",
                "topics": {},
            },
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
