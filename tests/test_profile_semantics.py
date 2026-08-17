from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nodrix.profiles import (
    PROFILE_DEFAULTS,
    RUNTIME_PRESET_DEFAULTS,
    get_profile,
    get_runtime_preset,
    profile_names,
    runtime_preset_names,
)
from nodrix.project_foundation import (
    add_project_resource,
    create_progressive_project,
    resolve_project_resource,
)


def test_runtime_preset_has_distinct_canonical_name() -> None:
    assert (
        "realtime-low-latency"
        in runtime_preset_names()
    )

    assert (
        "maximum-throughput"
        in runtime_preset_names()
    )


def test_legacy_profile_api_remains_runtime_preset_compatible() -> None:
    assert PROFILE_DEFAULTS is RUNTIME_PRESET_DEFAULTS

    assert (
        profile_names()
        == runtime_preset_names()
    )

    assert (
        get_profile("debug")
        == get_runtime_preset("debug")
    )


def test_runtime_preset_returns_independent_configuration() -> None:
    first = get_runtime_preset(
        "realtime-low-latency"
    )
    second = get_runtime_preset(
        "realtime-low-latency"
    )

    first["runtime"]["mode"] = "changed"

    assert (
        second["runtime"]["mode"]
        == "realtime"
    )


def test_unknown_runtime_preset_uses_runtime_preset_terminology() -> None:
    with pytest.raises(
        ValueError,
        match="Unknown Plyctl runtime preset",
    ):
        get_runtime_preset(
            "mid360s"
        )


def test_project_profile_is_not_a_runtime_preset(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    profile = add_project_resource(
        "profile",
        "mid360s",
        root=tmp_path,
        make_default=True,
    )

    document = yaml.safe_load(
        profile.path.read_text(
            encoding="utf-8"
        )
    )

    assert document == {
        "schema": "nodrix.profile/v1",
        "name": "mid360s",
        "variables": {},
    }

    assert (
        "mid360s"
        not in runtime_preset_names()
    )

    resolved = resolve_project_resource(
        "profile",
        root=tmp_path,
    )

    assert resolved.name == "mid360s"
    assert resolved.path == profile.path


def test_project_profile_can_select_runtime_preset(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    profile = add_project_resource(
        "profile",
        "robot",
        root=tmp_path,
    )

    profile.path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.profile/v1",
                "name": "robot",
                "runtime_profile": (
                    "realtime-low-latency"
                ),
                "variables": {
                    "ROBOT_MODEL": "rpi5",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    document = yaml.safe_load(
        profile.path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        document["runtime_profile"]
        == "realtime-low-latency"
    )

    assert (
        document["runtime_profile"]
        in runtime_preset_names()
    )


def test_project_profile_without_config_keeps_empty_system_config(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    profile = add_project_resource(
        "profile",
        "default",
        root=tmp_path,
        make_default=True,
    )

    from nodrix.project_foundation import (
        resolve_project_profile_config,
    )

    resolved = resolve_project_profile_config(
        root=tmp_path,
    )

    assert resolved.name == "default"
    assert resolved.path == profile.path
    assert resolved.config == {}

    # Backward compatibility: creating a Profile still does not
    # eagerly add a new config field to the document.
    document = yaml.safe_load(
        profile.path.read_text(
            encoding="utf-8"
        )
    )

    assert document == {
        "schema": "nodrix.profile/v1",
        "name": "default",
        "variables": {},
    }


def test_project_profile_can_declare_semantic_system_config(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    profile = add_project_resource(
        "profile",
        "rpi5",
        root=tmp_path,
    )

    profile.path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.profile/v1",
                "name": "rpi5",
                "variables": {
                    "ROBOT_MODEL": "rpi5",
                },
                "runtime_profile": (
                    "realtime-low-latency"
                ),
                "config": {
                    "mapping": {
                        "voxel_size_m": 0.1,
                        "point_stride": 1,
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from nodrix.project_foundation import (
        resolve_project_profile_config,
    )

    resolved = resolve_project_profile_config(
        "rpi5",
        root=tmp_path,
    )

    assert resolved.config == {
        "mapping": {
            "voxel_size_m": 0.1,
            "point_stride": 1,
        },
    }

    # Existing Profile responsibilities remain independent.
    document = yaml.safe_load(
        profile.path.read_text(
            encoding="utf-8"
        )
    )

    assert document["variables"] == {
        "ROBOT_MODEL": "rpi5",
    }

    assert (
        document["runtime_profile"]
        == "realtime-low-latency"
    )


def test_project_profile_config_must_be_mapping(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    profile = add_project_resource(
        "profile",
        "broken",
        root=tmp_path,
    )

    profile.path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.profile/v1",
                "name": "broken",
                "variables": {},
                "config": [
                    "not",
                    "a",
                    "mapping",
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from nodrix.project_foundation import (
        resolve_project_profile_config,
    )

    with pytest.raises(
        ValueError,
        match="config.*must be a YAML mapping",
    ):
        resolve_project_profile_config(
            "broken",
            root=tmp_path,
        )


def test_project_profile_config_requires_profile_schema(
    tmp_path: Path,
) -> None:
    create_progressive_project(
        tmp_path
    )

    profile = add_project_resource(
        "profile",
        "broken",
        root=tmp_path,
    )

    profile.path.write_text(
        yaml.safe_dump(
            {
                "schema": "wrong.schema/v1",
                "name": "broken",
                "variables": {},
                "config": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from nodrix.project_foundation import (
        resolve_project_profile_config,
    )

    with pytest.raises(
        ValueError,
        match="nodrix.profile/v1",
    ):
        resolve_project_profile_config(
            "broken",
            root=tmp_path,
        )
