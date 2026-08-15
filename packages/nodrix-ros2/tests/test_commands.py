from nodrix_ros2.commands import (
    build_ros2_launch_command,
    build_ros2_run_command,
    build_rviz_command,
)


def test_ros2_run_command_maps_parameters_without_shell() -> None:
    command = build_ros2_run_command(
        {
            "package": "demo_nodes_cpp",
            "executable": "talker",
            "name": "camera",
            "namespace": "/sensors",
            "ros_parameters": {"enabled": True, "rate": 30},
            "remappings": {"image": "/camera/image_raw"},
        }
    )
    assert command[:4] == ("ros2", "run", "demo_nodes_cpp", "talker")
    assert "__node:=camera" in command
    assert "image:=/camera/image_raw" in command
    assert "enabled:=true" in command


def test_ros_parameter_strings_keep_their_type() -> None:
    command = build_ros2_run_command(
        {
            "package": "demo_nodes_cpp",
            "executable": "talker",
            "ros_parameters": {"label": "true"},
            "params_files": ["robot.yaml"],
        }
    )
    assert 'label:="true"' in command
    assert command[command.index("--params-file") + 1] == "robot.yaml"


def test_launch_and_rviz_commands_are_explicit_argv() -> None:
    launch = build_ros2_launch_command(
        {
            "package": "fast_livo",
            "launch_file": "mapping.launch.py",
            "arguments": {"rviz": False, "config_file": "config.yaml"},
        }
    )
    assert launch == (
        "ros2",
        "launch",
        "fast_livo",
        "mapping.launch.py",
        "rviz:=false",
        "config_file:=config.yaml",
    )
    assert build_rviz_command({"config": "view.rviz"})[:3] == (
        "rviz2",
        "-d",
        "view.rviz",
    )
