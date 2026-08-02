import os
from pathlib import Path
import sys

from nodrix import NodeContext, SessionContext
from nodrix_ros2.nodes.topic_monitor import Ros2TopicMonitor
from nodrix_ros2.session import Ros2Session
from nodrix_ros2.workspace import WorkspacePreparation


class FakeGraph:
    def snapshot(self) -> dict:
        return {
            "status": "ok",
            "updated_ns": __import__("time").time_ns(),
            "topics": {
                "/cloud": {
                    "types": ["sensor_msgs/msg/PointCloud2"],
                    "publishers": 1,
                    "subscribers": 0,
                }
            },
        }


class FakeSession:
    graph = FakeGraph()


def test_graph_monitor_does_not_import_or_subscribe_to_message_type(
    tmp_path: Path,
) -> None:
    monitor = Ros2TopicMonitor(
        {
            "mode": "graph",
            "topic": "/cloud",
            "message_type": "sensor_msgs/msg/PointCloud2",
            "sample_interval_s": 0.05,
        }
    )
    monitor.open(
        NodeContext(
            name="cloud",
            run_dir=tmp_path,
            project_dir=tmp_path,
            runtime_mode="realtime",
            bindings={"session": FakeSession()},
        )
    )
    produced = monitor.produce()
    message = next(produced)["status"]
    monitor.close()
    assert message.payload["ready"] is True
    assert message.payload["mode"] == "graph"
    assert message.payload["received"] is None


def test_python_environment_activation_is_reversible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    python_path = tmp_path / "ros-python"
    python_path.mkdir()
    monkeypatch.setenv("NODRIX_ROS_TEST", "before")
    session = Ros2Session()
    session.context = SessionContext(
        name="ros",
        run_dir=tmp_path,
        project_dir=tmp_path,
        runtime_mode="realtime",
    )
    session.preparation = WorkspacePreparation(
        environment={
            "NODRIX_ROS_TEST": "active",
            "PYTHONPATH": str(python_path),
        },
        setup_files=(),
        built=False,
        fingerprint=None,
    )

    session.activate_python_environment()
    session.activate_python_environment()
    assert os.environ["NODRIX_ROS_TEST"] == "active"
    assert str(python_path) in sys.path

    session.close()
    assert os.environ["NODRIX_ROS_TEST"] == "before"
    assert str(python_path) not in sys.path
