from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fast_livo2_deployment.py"
SPEC = importlib.util.spec_from_file_location("fast_livo2_deployment", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_static_bundle_is_valid_before_network_pin() -> None:
    MODULE.validate_bundle(allow_unpinned=True)


def test_production_validation_requires_exact_commit() -> None:
    with pytest.raises(MODULE.ValidationError, match="not pinned"):
        MODULE.validate_bundle(allow_unpinned=False)


def test_reference_contract_matches_candidate_topics() -> None:
    contract = load(ROOT / "deployment" / "reference-contract.yaml")
    inputs = {item["role"]: item for item in contract["inputs"]}
    outputs = {item["role"]: item for item in contract["outputs"]}
    assert inputs["camera"] == {
        "role": "camera",
        "topic": "/camera/left/jpeg",
        "message_type": "sensor_msgs/msg/CompressedImage",
        "required": True,
    }
    assert outputs["odometry"]["topic"] == "/aft_mapped_to_init"
    assert outputs["metric_map"]["topic"] == "/Laser_map"


def test_replay_uses_native_player_with_startup_delay() -> None:
    pipeline = load(ROOT / "pipelines" / "replay-ros2.yaml")
    player = pipeline["applications"]["bag_player"]["parameters"]
    assert player["package"] == "rosbag2_transport"
    assert player["executable"] == "player"
    assert player["allow_clean_exit"] is True
    assert player["ros_parameters"]["play.delay.sec"] >= 5
    assert player["ros_parameters"]["play.disable_loan_message"] is False


def test_bag_metadata_check_accepts_exact_input_contract(tmp_path: Path) -> None:
    metadata = {
        "rosbag2_bagfile_information": {
            "topics_with_message_count": [
                {
                    "topic_metadata": {
                        "name": "/livox/lidar",
                        "type": "livox_ros_driver2/msg/CustomMsg",
                    },
                    "message_count": 1,
                },
                {
                    "topic_metadata": {
                        "name": "/livox/imu",
                        "type": "sensor_msgs/msg/Imu",
                    },
                    "message_count": 1,
                },
                {
                    "topic_metadata": {
                        "name": "/camera/left/jpeg",
                        "type": "sensor_msgs/msg/CompressedImage",
                    },
                    "message_count": 1,
                },
            ]
        }
    }
    (tmp_path / "metadata.yaml").write_text(
        yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8"
    )
    MODULE.check_bag(tmp_path)


def test_bag_metadata_check_rejects_wrong_camera_type(tmp_path: Path) -> None:
    metadata = {
        "rosbag2_bagfile_information": {
            "topics_with_message_count": [
                {
                    "topic_metadata": {
                        "name": "/livox/lidar",
                        "type": "livox_ros_driver2/msg/CustomMsg",
                    }
                },
                {
                    "topic_metadata": {
                        "name": "/livox/imu",
                        "type": "sensor_msgs/msg/Imu",
                    }
                },
                {
                    "topic_metadata": {
                        "name": "/camera/left/jpeg",
                        "type": "sensor_msgs/msg/Image",
                    }
                },
            ]
        }
    }
    (tmp_path / "metadata.yaml").write_text(
        yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(MODULE.ValidationError, match="type mismatch"):
        MODULE.check_bag(tmp_path)
