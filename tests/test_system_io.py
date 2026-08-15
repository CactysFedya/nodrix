from __future__ import annotations

import json
from pathlib import Path

import pytest

import nodrix
from nodrix.system import (
    Connection,
    Graph,
    NodeInstance,
    ResourceInstance,
    SystemFormatError,
    SystemModel,
    Target,
    dump_system,
    dumps_system,
    load_system,
    load_system_details,
    loads_system,
    system_json_schema,
    system_to_canonical,
)


def _system() -> SystemModel:
    return SystemModel(
        name="robot-mapping",
        description="Canonical 2.5 System document",
        resources=(
            ResourceInstance(
                name="main_gpu",
                uses="compute.gpu",
                parameters={"index": 0},
            ),
        ),
        targets=(
            Target(
                name="raspberry_pi",
                kind="host",
                properties={"arch": "aarch64", "os": "linux"},
            ),
        ),
        graphs=(
            Graph(
                name="perception",
                nodes=(
                    NodeInstance(name="source", uses="vision.source"),
                    NodeInstance(
                        name="detector",
                        uses="vision.detect",
                        parameters={"threshold": 0.4, "max_det": 50},
                        resources={"gpu": "main_gpu"},
                        target="raspberry_pi",
                    ),
                ),
                connections=(
                    Connection(
                        **{
                            "from": "source.output",
                            "to": "detector.image",
                            "type_id": "vision.image/v1",
                        }
                    ),
                ),
            ),
        ),
        metadata={"owner": "tests"},
    )


def test_yaml_round_trip_is_canonical(tmp_path: Path) -> None:
    system = _system()
    path = tmp_path / "system.yaml"

    dump_system(system, path)
    text = path.read_text(encoding="utf-8")

    assert text.startswith(
        "apiVersion: nodrix.system/v1\nkind: System\nname: robot-mapping\n"
    )
    assert "api_version" not in text
    assert "source:" not in text
    assert "from: source.output" in text
    assert "to: detector.image" in text

    loaded = load_system(path)
    assert loaded == system

    details = load_system_details(path)
    assert details.system == system
    assert details.format == "yaml"
    assert details.canonical == system_to_canonical(system)


def test_json_round_trip(tmp_path: Path) -> None:
    system = _system()
    path = tmp_path / "system.json"

    dump_system(system, path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert raw["apiVersion"] == "nodrix.system/v1"
    assert raw["kind"] == "System"
    assert raw["graphs"][0]["connections"][0]["from"] == "source.output"

    assert load_system(path) == system
    assert loads_system(dumps_system(system, format="json"), format="json") == system


def test_canonical_representation_omits_default_empty_sections() -> None:
    canonical = system_to_canonical(SystemModel(name="minimal"))

    assert canonical == {
        "apiVersion": "nodrix.system/v1",
        "kind": "System",
        "name": "minimal",
    }


def test_loader_rejects_missing_api_version() -> None:
    with pytest.raises(SystemFormatError) as exc_info:
        loads_system("kind: System\nname: broken\n")

    assert exc_info.value.code == "SYSFMT002"
    assert exc_info.value.location == "apiVersion"


def test_loader_rejects_unknown_api_version() -> None:
    with pytest.raises(SystemFormatError) as exc_info:
        loads_system(
            "apiVersion: nodrix.system/v999\n"
            "kind: System\n"
            "name: future\n"
        )

    assert exc_info.value.code == "SYSFMT003"
    assert "nodrix.system/v999" in str(exc_info.value)


def test_loader_rejects_wrong_kind() -> None:
    with pytest.raises(SystemFormatError) as exc_info:
        loads_system(
            "apiVersion: nodrix.system/v1\n"
            "kind: Pipeline\n"
            "name: wrong\n"
        )

    assert exc_info.value.code == "SYSFMT003"
    assert exc_info.value.location == "kind"


def test_loader_preserves_strict_extra_forbid() -> None:
    with pytest.raises(SystemFormatError) as exc_info:
        loads_system(
            "apiVersion: nodrix.system/v1\n"
            "kind: System\n"
            "name: strict\n"
            "unknownField: true\n"
        )

    assert exc_info.value.code == "SYSFMT006"
    assert "unknownField" in str(exc_info.value)


def test_json_schema_uses_public_aliases_and_is_checked_in() -> None:
    schema = system_json_schema()
    properties = schema["properties"]

    assert schema["$id"] == "urn:nodrix:schema:system:v1"
    assert "apiVersion" in properties
    assert "api_version" not in properties
    assert properties["apiVersion"]["const"] == "nodrix.system/v1"
    assert properties["kind"]["const"] == "System"

    package_schema = (
        Path(nodrix.__file__).resolve().parent
        / "schemas"
        / "system-v1.schema.json"
    )
    assert json.loads(package_schema.read_text(encoding="utf-8")) == schema


def test_public_plyctl_facade_exports_system_io() -> None:
    from plyctl import dump_system as public_dump_system
    from plyctl import load_system as public_load_system

    assert public_dump_system is dump_system
    assert public_load_system is load_system
