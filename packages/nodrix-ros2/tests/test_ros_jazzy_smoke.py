import os
import threading

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("ROS_DISTRO") != "jazzy",
    reason="requires a sourced ROS 2 Jazzy environment",
)


def test_shared_executor_transfers_one_message() -> None:
    from std_msgs.msg import String
    from nodrix_ros2.context import SharedRosRuntime

    runtime = SharedRosRuntime()
    publisher_lease = runtime.acquire_node(name="nodrix_smoke_publisher")
    subscriber_lease = runtime.acquire_node(name="nodrix_smoke_subscriber")
    received = threading.Event()
    subscription = subscriber_lease.node.create_subscription(
        String,
        "/nodrix/ci_smoke",
        lambda message: received.set() if message.data == "ready" else None,
        10,
    )
    publisher = publisher_lease.node.create_publisher(
        String,
        "/nodrix/ci_smoke",
        10,
    )
    try:
        message = String()
        message.data = "ready"
        for _ in range(10):
            publisher.publish(message)
            if received.wait(0.2):
                break
        assert received.is_set()
    finally:
        subscriber_lease.node.destroy_subscription(subscription)
        publisher_lease.node.destroy_publisher(publisher)
        subscriber_lease.close()
        publisher_lease.close()
