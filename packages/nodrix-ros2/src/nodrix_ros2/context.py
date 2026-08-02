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
        self._condition = threading.Condition(self._lock)
        self._rclpy: Any | None = None
        self._context: Any | None = None
        self._executor: Any | None = None
        self._thread: threading.Thread | None = None
        self._nodes: dict[int, Any] = {}
        self._tearing_down = False
        self._executor_error: BaseException | None = None
        self._executor_threads: int | None = None

    def _start_locked(self, executor_threads: int) -> None:
        if self._context is not None:
            if self._executor_error is not None:
                raise RuntimeError(
                    f"ROS executor stopped unexpectedly: {self._executor_error}"
                ) from self._executor_error
            if self._executor_threads != max(int(executor_threads), 1):
                raise RuntimeError(
                    "All nodes sharing one ROS runtime must use the same "
                    f"executor_threads (active={self._executor_threads}, "
                    f"requested={max(int(executor_threads), 1)})"
                )
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
        try:
            executor = executors.MultiThreadedExecutor(
                num_threads=max(int(executor_threads), 1),
                context=context,
            )
        except BaseException:
            try:
                rclpy.shutdown(context=context)
            except Exception:
                pass
            raise

        self._rclpy = rclpy
        self._context = context
        self._executor = executor
        self._executor_error = None
        self._executor_threads = max(int(executor_threads), 1)

        def spin() -> None:
            try:
                executor.spin()
                error: BaseException = RuntimeError(
                    "ROS executor returned without a shutdown request"
                )
            except BaseException as exc:
                error = exc
            with self._condition:
                if self._executor is executor:
                    self._executor_error = error
                    self._condition.notify_all()

        self._thread = threading.Thread(
            target=spin,
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
        resources: tuple[
            Any, Any, Any, threading.Thread | None, tuple[Any, ...]
        ] | None = None
        error: BaseException | None = None
        node: Any | None = None
        with self._condition:
            while self._tearing_down:
                self._condition.wait()
            self._start_locked(executor_threads)
            assert self._rclpy is not None
            assert self._context is not None
            assert self._executor is not None
            try:
                node = self._rclpy.create_node(
                    str(name),
                    namespace=str(namespace),
                    context=self._context,
                )
                self._executor.add_node(node)
                self._nodes[id(node)] = node
            except BaseException as exc:
                error = exc
                if node is not None:
                    try:
                        node.destroy_node()
                    except Exception:
                        pass
                if not self._nodes:
                    self._tearing_down = True
                    resources = self._detach_locked()
        if resources is not None:
            self._finish_shutdown(resources)
        if error is not None:
            raise error
        assert node is not None
        return RosNodeLease(self, node)

    def release_node(self, node: Any) -> None:
        resources: tuple[
            Any, Any, Any, threading.Thread | None, tuple[Any, ...]
        ] | None = None
        destroy_error: BaseException | None = None
        with self._condition:
            if self._nodes.pop(id(node), None) is None:
                return
            if self._executor is not None:
                try:
                    self._executor.remove_node(node)
                except Exception:
                    pass
            try:
                node.destroy_node()
            except BaseException as exc:
                destroy_error = exc
            if not self._nodes:
                self._tearing_down = True
                resources = self._detach_locked()

        if resources is not None:
            self._finish_shutdown(resources)
        if destroy_error is not None:
            raise destroy_error

    def _detach_locked(
        self,
    ) -> tuple[Any, Any, Any, threading.Thread | None, tuple[Any, ...]]:
        resources = (
            self._executor,
            self._context,
            self._rclpy,
            self._thread,
            tuple(self._nodes.values()),
        )
        self._nodes.clear()
        self._executor = None
        self._context = None
        self._rclpy = None
        self._thread = None
        self._executor_threads = None
        self._executor_error = None
        return resources

    def _finish_shutdown(
        self,
        resources: tuple[
            Any, Any, Any, threading.Thread | None, tuple[Any, ...]
        ],
    ) -> None:
        executor, context, rclpy, thread, nodes = resources
        try:
            for node in nodes:
                if executor is not None:
                    try:
                        executor.remove_node(node)
                    except Exception:
                        pass
                try:
                    node.destroy_node()
                except Exception:
                    pass
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
        finally:
            with self._condition:
                self._tearing_down = False
                self._condition.notify_all()

    def shutdown(self) -> None:
        with self._condition:
            while self._tearing_down:
                self._condition.wait()
            self._tearing_down = True
            executor = self._executor
            resources = self._detach_locked()
        if executor is None:
            with self._condition:
                self._tearing_down = False
                self._condition.notify_all()
            return
        self._finish_shutdown(resources)

    def health(self) -> dict[str, Any]:
        with self._condition:
            return {
                "status": (
                    "error"
                    if self._executor_error is not None
                    else "running"
                    if self._context is not None
                    else "idle"
                ),
                "nodes": len(self._nodes),
                "executor_threads": self._executor_threads,
                "tearing_down": self._tearing_down,
                "error": (
                    None
                    if self._executor_error is None
                    else f"{type(self._executor_error).__name__}: "
                    f"{self._executor_error}"
                ),
            }


_SHARED_RUNTIME = SharedRosRuntime()


def shared_ros_runtime() -> SharedRosRuntime:
    return _SHARED_RUNTIME
