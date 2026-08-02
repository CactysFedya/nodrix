import threading
import time
from types import SimpleNamespace

from nodrix_ros2.context import SharedRosRuntime
import nodrix_ros2.context as ros_context


class FakeContext:
    def shutdown(self) -> None:
        pass


class FakeNode:
    def __init__(self, name: str) -> None:
        self.name = name
        self.destroyed = False

    def destroy_node(self) -> None:
        self.destroyed = True


class FakeExecutor:
    shutdown_started = threading.Event()
    allow_shutdown = threading.Event()

    def __init__(self, *, num_threads: int, context: FakeContext) -> None:
        self.num_threads = num_threads
        self.context = context
        self.stopped = threading.Event()

    def add_node(self, node: FakeNode) -> None:
        pass

    def remove_node(self, node: FakeNode) -> None:
        pass

    def spin(self) -> None:
        self.stopped.wait(5)

    def shutdown(self, timeout_sec: float) -> None:
        type(self).shutdown_started.set()
        type(self).allow_shutdown.wait(5)
        self.stopped.set()


class FakeRclpy:
    def init(self, *, args, context) -> None:
        pass

    def shutdown(self, *, context) -> None:
        pass

    def create_node(self, name: str, *, namespace: str, context) -> FakeNode:
        return FakeNode(name)


def _install_fake_rclpy(monkeypatch) -> None:
    FakeExecutor.shutdown_started.clear()
    FakeExecutor.allow_shutdown.clear()
    modules = {
        "rclpy": FakeRclpy(),
        "rclpy.context": SimpleNamespace(Context=FakeContext),
        "rclpy.executors": SimpleNamespace(MultiThreadedExecutor=FakeExecutor),
    }
    original = ros_context.importlib.import_module
    monkeypatch.setattr(
        ros_context.importlib,
        "import_module",
        lambda name: modules[name] if name in modules else original(name),
    )


def test_acquire_waits_for_last_node_teardown(monkeypatch) -> None:
    _install_fake_rclpy(monkeypatch)
    runtime = SharedRosRuntime()
    first = runtime.acquire_node(name="first", executor_threads=3)
    released = threading.Thread(target=first.close)
    released.start()
    assert FakeExecutor.shutdown_started.wait(1)

    acquired: list = []
    waiter = threading.Thread(
        target=lambda: acquired.append(
            runtime.acquire_node(name="second", executor_threads=3)
        )
    )
    waiter.start()
    time.sleep(0.05)
    assert acquired == []
    FakeExecutor.allow_shutdown.set()
    released.join(2)
    waiter.join(2)
    assert len(acquired) == 1
    acquired[0].close()


def test_shutdown_destroys_live_nodes(monkeypatch) -> None:
    _install_fake_rclpy(monkeypatch)
    FakeExecutor.allow_shutdown.set()
    runtime = SharedRosRuntime()
    lease = runtime.acquire_node(name="live")
    runtime.shutdown()
    assert lease.node.destroyed is True
    assert runtime.health()["status"] == "idle"
