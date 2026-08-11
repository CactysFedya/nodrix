from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.system import (
    Graph,
    NodeInstance,
    SystemModel,
    Target,
    dump_system,
    load_system,
)


runner = CliRunner()


def test_system_cli_help_lists_m5_commands() -> None:
    result = runner.invoke(app, ["system", "--help"])

    assert result.exit_code == 0, result.output
    assert "validate" in result.output
    assert "show" in result.output
    assert "convert" in result.output
    assert "schema" in result.output


def test_system_validate_accepts_valid_document(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    dump_system(
        SystemModel(
            name="valid-system",
            targets=(Target(name="local", kind="host"),),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="worker",
                            uses="demo.worker",
                            target="local",
                        ),
                    ),
                ),
            ),
        ),
        path,
    )

    result = runner.invoke(app, ["system", "validate", str(path)])

    assert result.exit_code == 0, result.output
    assert "NODRIX SYSTEM valid-system" in result.output
    assert "VALID" in result.output
    assert "contracts and references are valid" in result.output


def test_system_validate_rejects_bad_reference(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    dump_system(
        SystemModel(
            name="bad-system",
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="worker",
                            uses="demo.worker",
                            target="missing",
                        ),
                    ),
                ),
            ),
        ),
        path,
    )

    result = runner.invoke(app, ["system", "validate", str(path)])

    assert result.exit_code == 1
    assert "INVALID" in result.output
    assert "SYS011" in result.output


def test_system_show_json_returns_canonical_document(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    dump_system(SystemModel(name="shown"), path)

    result = runner.invoke(
        app,
        ["system", "show", str(path), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["apiVersion"] == "nodrix.system/v1"
    assert payload["kind"] == "System"
    assert payload["name"] == "shown"


def test_system_show_summary_reports_architecture_counts(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    dump_system(
        SystemModel(
            name="summary",
            graphs=(
                Graph(
                    name="mapping",
                    nodes=(
                        NodeInstance(name="source", uses="mapping.source"),
                        NodeInstance(name="sink", uses="mapping.sink"),
                    ),
                ),
            ),
        ),
        path,
    )

    result = runner.invoke(app, ["system", "show", str(path)])

    assert result.exit_code == 0, result.output
    assert "NODRIX SYSTEM summary" in result.output
    assert "Shape" in result.output
    assert "mapping" in result.output


def test_system_convert_writes_loadable_system_and_report(tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(
        yaml.safe_dump(
            {
                "metadata": {"name": "legacy"},
                "runtime": {"engine": "unified"},
                "nodes": {
                    "source": {"uses": "demo.source"},
                    "sink": {"uses": "demo.sink"},
                },
                "edges": [
                    {"from": "source.output", "to": "sink.input"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "system.yaml"

    result = runner.invoke(
        app,
        [
            "system",
            "convert",
            str(pipeline),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.is_file()
    system = load_system(output)
    assert system.name == "legacy"
    assert system.graph("main").node("source").uses == "demo.source"
    assert "NODRIX CONVERT legacy" in result.output
    assert "Lossless" in result.output
    assert "True" in result.output
    assert "0 unsupported" in result.output


def test_system_convert_refuses_overwrite_without_force(tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(
        yaml.safe_dump(
            {
                "metadata": {"name": "legacy"},
                "runtime": {"engine": "unified"},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "system.yaml"
    output.write_text("do-not-overwrite\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "system",
            "convert",
            str(pipeline),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert "CONVERSION FAILED" in result.output
    assert "already exists" in result.output
    assert output.read_text(encoding="utf-8") == "do-not-overwrite\n"


def test_system_schema_prints_current_schema() -> None:
    result = runner.invoke(app, ["system", "schema"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["$id"] == "urn:nodrix:schema:system:v1"
    assert payload["properties"]["apiVersion"]["const"] == "nodrix.system/v1"


def test_system_schema_can_write_file(tmp_path: Path) -> None:
    output = tmp_path / "system.schema.json"

    result = runner.invoke(
        app,
        ["system", "schema", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    assert "SCHEMA WRITTEN" in result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["title"] == "Nodrix System Model v1"


def test_system_validate_with_project_resolves_sdk_definitions(tmp_path: Path) -> None:
    project = tmp_path / "project"
    components = project / "components"
    components.mkdir(parents=True)

    (components / "types.py").write_text(
        "from dataclasses import dataclass\n"
        "from plyctl import message\n\n"
        "@message\n"
        "@dataclass(frozen=True)\n"
        "class Frame:\n"
        "    value: int\n",
        encoding="utf-8",
    )
    (components / "nodes.py").write_text(
        "from plyctl import node\n"
        "from components.types import Frame\n\n"
        "@node\n"
        "def source() -> Frame:\n"
        "    return Frame(1)\n\n"
        "@node\n"
        "def sink(image: Frame) -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )

    # The System intentionally uses the wrong target input port. Structural
    # validation alone cannot know this; --project must resolve NodeDefinitions.
    system_path = project / "system.yaml"
    dump_system(
        SystemModel(
            name="typed",
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(name="source", uses="local.source"),
                        NodeInstance(name="sink", uses="local.sink"),
                    ),
                    connections=(
                        {
                            "from": "source.output",
                            "to": "sink.missing",
                        },
                    ),
                ),
            ),
        ),
        system_path,
    )

    result = runner.invoke(
        app,
        [
            "system",
            "validate",
            str(system_path),
            "--project",
            str(project),
        ],
    )

    assert result.exit_code == 1
    assert "SYS132" in result.output
