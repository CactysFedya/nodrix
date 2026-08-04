#!/usr/bin/env python3
"""Pin and validate the FAST-LIVO2 reference deployment without importing ROS."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment-specific error path
    raise SystemExit("PyYAML is required: python -m pip install PyYAML") from exc

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "deployment" / "fast-livo2.lock.yaml"
CONTRACT_PATH = ROOT / "deployment" / "reference-contract.yaml"
PLATFORMS_PATH = ROOT / "deployment" / "supported-platforms.yaml"
PIPELINE_PATH = ROOT / "pipelines" / "replay-ros2.yaml"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class ValidationError(RuntimeError):
    """Raised when deployment metadata is internally inconsistent."""


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationError(f"Cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValidationError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"Expected a YAML mapping in {path}")
    return value


def _write_yaml(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        yaml.safe_dump(dict(value), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{path} must be a mapping")
    return dict(value)


def _sequence(value: Any, path: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValidationError(f"{path} must be an array")
    return list(value)


def _role_map(entries: Any, path: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_sequence(entries, path)):
        item = _mapping(raw, f"{path}[{index}]")
        role = str(item.get("role", "")).strip()
        topic = str(item.get("topic", "")).strip()
        message_type = str(item.get("message_type", "")).strip()
        if not role or not topic.startswith("/") or "/" not in message_type:
            raise ValidationError(f"Invalid role/topic/type in {path}[{index}]")
        if role in result:
            raise ValidationError(f"Duplicate role {role!r} in {path}")
        result[role] = item
    return result


def _edge_contracts(pipeline: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, raw in enumerate(_sequence(pipeline.get("edges", []), "pipeline.edges")):
        edge = _mapping(raw, f"pipeline.edges[{index}]")
        transport = _mapping(edge.get("transport"), f"pipeline.edges[{index}].transport")
        parameters = _mapping(
            transport.get("parameters"),
            f"pipeline.edges[{index}].transport.parameters",
        )
        topic = str(parameters.get("topic", "")).strip()
        message_type = str(parameters.get("message_type", "")).strip()
        if topic:
            result[topic] = message_type
    return result


def validate_bundle(*, allow_unpinned: bool = False) -> None:
    lock = _load_yaml(LOCK_PATH)
    contract = _load_yaml(CONTRACT_PATH)
    platforms = _load_yaml(PLATFORMS_PATH)
    pipeline = _load_yaml(PIPELINE_PATH)

    if lock.get("schema_version") != 1:
        raise ValidationError("Unsupported lock schema_version")
    implementation = _mapping(lock.get("implementation"), "implementation")
    source = _mapping(implementation.get("source"), "implementation.source")
    repository = str(source.get("repository", ""))
    requested_ref = str(source.get("requested_ref", ""))
    resolved_commit = source.get("resolved_commit")
    if repository != "https://github.com/v4rl-ucy/FAST-LIVO2-ROS2.git":
        raise ValidationError("Unexpected FAST-LIVO2 candidate repository")
    if not requested_ref.startswith("refs/"):
        raise ValidationError("implementation.source.requested_ref must be a full ref")
    if resolved_commit is None:
        if not allow_unpinned:
            raise ValidationError(
                "FAST-LIVO2 is not pinned; run the 'pin' command before committing"
            )
    elif not SHA1_RE.fullmatch(str(resolved_commit)):
        raise ValidationError("resolved_commit must be a 40-character lowercase SHA-1")

    launch = _mapping(implementation.get("launch"), "implementation.launch")
    if implementation.get("package") != "fast_livo":
        raise ValidationError("Pinned package must be fast_livo")
    if launch.get("file") != "mapping_aviz_metacamedu.launch.py":
        raise ValidationError("Pinned launch file does not match the reference profile")
    license_info = _mapping(implementation.get("license"), "implementation.license")
    if license_info.get("spdx") != "GPL-2.0-only":
        raise ValidationError("FAST-LIVO2 license metadata must remain explicit")

    inputs = _role_map(contract.get("inputs"), "contract.inputs")
    outputs = _role_map(contract.get("outputs"), "contract.outputs")
    expected_inputs = {
        "lidar": ("/livox/lidar", "livox_ros_driver2/msg/CustomMsg"),
        "imu": ("/livox/imu", "sensor_msgs/msg/Imu"),
        "camera": ("/camera/left/jpeg", "sensor_msgs/msg/CompressedImage"),
    }
    expected_outputs = {
        "registered_cloud": ("/cloud_registered", "sensor_msgs/msg/PointCloud2"),
        "metric_map": ("/Laser_map", "sensor_msgs/msg/PointCloud2"),
        "odometry": ("/aft_mapped_to_init", "nav_msgs/msg/Odometry"),
    }
    for role, (topic, message_type) in {**expected_inputs, **expected_outputs}.items():
        source_map = inputs if role in expected_inputs else outputs
        item = source_map.get(role)
        if item is None:
            raise ValidationError(f"Missing required role {role!r}")
        if (item.get("topic"), item.get("message_type")) != (topic, message_type):
            raise ValidationError(f"Contract mismatch for role {role!r}")

    applications = _mapping(pipeline.get("applications"), "pipeline.applications")
    player = _mapping(applications.get("bag_player"), "applications.bag_player")
    player_parameters = _mapping(player.get("parameters"), "bag_player.parameters")
    if (player_parameters.get("package"), player_parameters.get("executable")) != (
        "rosbag2_transport",
        "player",
    ):
        raise ValidationError("Replay must use the native rosbag2_transport player")
    if player_parameters.get("allow_clean_exit") is not True:
        raise ValidationError("Bag player must allow a clean end-of-bag exit")
    ros_parameters = _mapping(
        player_parameters.get("ros_parameters"), "bag_player.ros_parameters"
    )
    if ros_parameters.get("storage.uri") != "${FAST_LIVO2_BAG}":
        raise ValidationError("Replay bag path must come from FAST_LIVO2_BAG")
    if float(ros_parameters.get("play.delay.sec", 0)) < 5:
        raise ValidationError("Replay delay must leave time for FAST-LIVO2 subscribers")
    if float(ros_parameters.get("play.clock_publish_frequency", 0)) <= 0:
        raise ValidationError("Replay must publish /clock")
    if ros_parameters.get("play.disable_loan_message") is not False:
        raise ValidationError("Loaned-message playback must not be disabled by default")

    fast_livo2 = _mapping(applications.get("fast_livo2"), "applications.fast_livo2")
    fast_parameters = _mapping(fast_livo2.get("parameters"), "fast_livo2.parameters")
    if fast_parameters.get("package") != implementation.get("package"):
        raise ValidationError("Pipeline package differs from the deployment lock")
    if fast_parameters.get("launch_file") != launch.get("file"):
        raise ValidationError("Pipeline launch file differs from the deployment lock")

    edges = _edge_contracts(pipeline)
    for topic, message_type in expected_inputs.values():
        if edges.get(topic) != message_type:
            raise ValidationError(f"Missing typed replay edge for {topic}")

    monitors = _mapping(pipeline.get("nodes"), "pipeline.nodes")
    monitored_topics: dict[str, str] = {}
    for name, raw in monitors.items():
        node = _mapping(raw, f"pipeline.nodes.{name}")
        parameters = _mapping(node.get("parameters"), f"pipeline.nodes.{name}.parameters")
        topic = str(parameters.get("topic", ""))
        if topic:
            monitored_topics[topic] = str(parameters.get("message_type", ""))
    for topic, message_type in [*expected_inputs.values(), *expected_outputs.values()]:
        if monitored_topics.get(topic) != message_type:
            raise ValidationError(f"Missing graph monitor for {topic}")

    platform_entries = _sequence(platforms.get("platforms"), "platforms")
    jazzy = [
        _mapping(item, "platform")
        for item in platform_entries
        if isinstance(item, Mapping) and item.get("id") == "nodrix-jazzy-amd64"
    ]
    if len(jazzy) != 1 or jazzy[0].get("status") != "experimental":
        raise ValidationError("Jazzy must remain experimental until evidence is recorded")


def pin_source() -> str:
    lock = _load_yaml(LOCK_PATH)
    implementation = _mapping(lock.get("implementation"), "implementation")
    source = _mapping(implementation.get("source"), "implementation.source")
    repository = str(source.get("repository", "")).strip()
    requested_ref = str(source.get("requested_ref", "")).strip()
    if not repository or not requested_ref:
        raise ValidationError("Repository and requested_ref are required")
    try:
        completed = subprocess.run(
            ["git", "ls-remote", "--exit-code", repository, requested_ref],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationError(f"Cannot resolve FAST-LIVO2 ref: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise ValidationError(f"git ls-remote failed: {detail}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValidationError(f"Expected one ref result, received {len(lines)}")
    commit = lines[0].split()[0].lower()
    if not SHA1_RE.fullmatch(commit):
        raise ValidationError(f"Invalid commit returned by git ls-remote: {commit!r}")
    source["resolved_commit"] = commit
    source["resolved_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    implementation["source"] = source
    lock["implementation"] = implementation
    _write_yaml(LOCK_PATH, lock)
    return commit


def _bag_topics(metadata: Mapping[str, Any]) -> dict[str, str]:
    info = metadata.get("rosbag2_bagfile_information", metadata)
    info_map = _mapping(info, "rosbag2_bagfile_information")
    entries = info_map.get("topics_with_message_count", [])
    result: dict[str, str] = {}
    for index, raw in enumerate(_sequence(entries, "topics_with_message_count")):
        entry = _mapping(raw, f"topics_with_message_count[{index}]")
        topic_metadata = _mapping(
            entry.get("topic_metadata"),
            f"topics_with_message_count[{index}].topic_metadata",
        )
        name = str(topic_metadata.get("name", "")).strip()
        message_type = str(topic_metadata.get("type", "")).strip()
        if name:
            result[name] = message_type
    return result


def check_bag(bag: Path) -> None:
    contract = _load_yaml(CONTRACT_PATH)
    required = _role_map(contract.get("inputs"), "contract.inputs")
    metadata_path = bag / "metadata.yaml" if bag.is_dir() else None
    if metadata_path is not None and metadata_path.is_file():
        metadata = _load_yaml(metadata_path)
    else:
        try:
            completed = subprocess.run(
                ["ros2", "bag", "info", "--yaml", str(bag)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValidationError(f"Cannot inspect rosbag: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"exit code {completed.returncode}"
            raise ValidationError(f"ros2 bag info failed: {detail}")
        parsed = yaml.safe_load(completed.stdout)
        if not isinstance(parsed, Mapping):
            raise ValidationError("ros2 bag info --yaml returned an invalid document")
        metadata = dict(parsed)

    topics = _bag_topics(metadata)
    missing: list[str] = []
    mismatched: list[str] = []
    for role, item in required.items():
        if not bool(item.get("required", False)):
            continue
        topic = str(item["topic"])
        expected = str(item["message_type"])
        actual = topics.get(topic)
        if actual is None:
            missing.append(f"{role}:{topic}")
        elif actual != expected:
            mismatched.append(f"{topic}: expected {expected}, got {actual}")
    if missing or mismatched:
        parts = []
        if missing:
            parts.append("missing " + ", ".join(missing))
        if mismatched:
            parts.append("type mismatch " + "; ".join(mismatched))
        raise ValidationError("Reference bag is incompatible: " + " | ".join(parts))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate deployment metadata")
    validate.add_argument("--allow-unpinned", action="store_true")
    subparsers.add_parser("pin", help="resolve requested_ref and update the lock file")
    bag_check = subparsers.add_parser("bag-check", help="validate reference bag topics")
    bag_check.add_argument("--bag", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            validate_bundle(allow_unpinned=bool(args.allow_unpinned))
            print("FAST-LIVO2 deployment metadata is valid")
        elif args.command == "pin":
            commit = pin_source()
            validate_bundle(allow_unpinned=False)
            print(f"Pinned FAST-LIVO2 to {commit}")
        elif args.command == "bag-check":
            check_bag(args.bag.expanduser().resolve())
            print(f"Reference bag is compatible: {args.bag}")
        else:  # pragma: no cover
            raise AssertionError(args.command)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
