from __future__ import annotations

from dataclasses import dataclass
import importlib
import threading
from typing import Any


@dataclass(slots=True)
class RosNodeLease:
    runtime: "SharedRosRuntime"
    node: Any
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.runtime.release_node(self.node)


class SharedRosRuntime:
    """One rclpy context and executor shared by all Nodrix ROS 2 blocks."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rclpy: Any | None = None
        self._context: Any | None = None
        self._executor: Any | None = None
        self._thread: threading.Thread | None = None
        self._nodes: dict[int, Any] = {}

    def _start_locked(self, executor_threads: int) -> None:
        if self._context is not None:
            return
        try:
            rclpy = importlib.import_module("rclpy")
            context_module = importlib.import_module("rclpy.context")
            executors = importlib.import_module("rclpy.executors")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "nodrix-ros2 requires a sourced ROS 2 installation with rclpy"
            ) from exc

        context = context_module.Context()
        rclpy.init(args=None, context=context)
        executor = executors.MultiThreadedExecutor(
            num_threads=max(int(executor_threads), 1),
            context=context,
        )

        self._rclpy = rclpy
        self._context = context
        self._executor = executor
        self._thread = threading.Thread(
            target=executor.spin,
            name="nodrix-ros2-executor",
            daemon=True,
        )
        self._thread.start()

    def acquire_node(
        self,
        *,
        name: str,
        namespace: str = "",
        executor_threads: int = 2,
    ) -> RosNodeLease:
        with self._lock:
            self._start_locked(executor_threads)
            assert self._rclpy is not None
            assert self._context is not None
            assert self._executor is not None
            node = self._rclpy.create_node(
                str(name),
                namespace=str(namespace),
                context=self._context,
            )
            self._executor.add_node(node)
            self._nodes[id(node)] = node
            return RosNodeLease(self, node)

    def release_node(self, node: Any) -> None:
        shutdown = False
        with self._lock:
            if self._nodes.pop(id(node), None) is None:
                return
            if self._executor is not None:
                try:
                    self._executor.remove_node(node)
                except Exception:
                    pass
            try:
                node.destroy_node()
            finally:
                shutdown = not self._nodes

        if shutdown:
            self.shutdown()

    def shutdown(self) -> None:
        with self._lock:
            executor = self._executor
            context = self._context
            rclpy = self._rclpy
            thread = self._thread
            self._executor = None
            self._context = None
            self._rclpy = None
            self._thread = None
            self._nodes.clear()

        if executor is not None:
            try:
                executor.shutdown(timeout_sec=2.0)
            except Exception:
                pass
        if rclpy is not None and context is not None:
            try:
                rclpy.shutdown(context=context)
            except Exception:
                try:
                    context.shutdown()
                except Exception:
                    pass
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)


_SHARED_RUNTIME = SharedRosRuntime()


def shared_ros_runtime() -> SharedRosRuntime:
    return _SHARED_RUNTIME
