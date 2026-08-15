import pytest

from nodrix_ros2.links import apply_topic_contracts, topic_contracts


LINKS = [
    {
        "from": "driver.scan",
        "to": "localization.input",
        "uses": "ros2.topic",
        "parameters": {
            "topic": "/scan",
            "message_type": "sensor_msgs/msg/LaserScan",
            "qos": {"reliability": "best_effort"},
        },
    }
]


def test_topic_contracts_compile_for_node_and_launch() -> None:
    incoming = topic_contracts(LINKS, node_name="localization")
    assert incoming[0].direction == "input"
    assert incoming[0].port == "input"
    assert incoming[0].topic == "/scan"
    node = apply_topic_contracts({}, process_kind="ros2.node", contracts=incoming)
    launch = apply_topic_contracts(
        {"ros_port_arguments": {"input": "scan_topic"}},
        process_kind="ros2.launch",
        contracts=incoming,
    )
    assert node["remappings"] == {"input": "/scan"}
    assert launch["arguments"] == {"scan_topic": "/scan"}


def test_topic_contracts_reject_invalid_and_conflicting_links() -> None:
    invalid = [dict(LINKS[0], to="localization")]
    with pytest.raises(ValueError, match="<node>.<port>"):
        topic_contracts(invalid, node_name="localization")

    conflict = LINKS + [
        {
            "from": "backup.scan",
            "to": "localization.input",
            "uses": "ros2.topic",
            "parameters": {
                "topic": "/backup_scan",
                "message_type": "sensor_msgs/msg/LaserScan",
            },
        }
    ]
    with pytest.raises(ValueError, match="Conflicting"):
        topic_contracts(conflict, node_name="localization")
