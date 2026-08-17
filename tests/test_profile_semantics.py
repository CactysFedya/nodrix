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
