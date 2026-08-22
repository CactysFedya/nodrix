from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nodrix import (
    ApplicationDescriptor,
    ApplicationContext,
    ManagedApplication,
    ManagedResource,
    ResourceContext,
    ResourceDescriptor,
)
from nodrix.hybrid_runtime import HybridPipelineRuntime
from nodrix.execution_plan import compile_execution_plan
from nodrix.manifest import PipelineManifest, load_manifest_details
from nodrix.cli import app
from nodrix.manifest_schema import manifest_json_schema, render_manifest_schema
from nodrix.migration import migrate_manifest


_LIFECYCLE_EVENTS: list[str] = []


class _RuntimeResource(ManagedResource):
    def open(self, context: ResourceContext) -> None:
        super().open(context)
        _LIFECYCLE_EVENTS.append("resource.open")

    def close(self) -> None:
        _LIFECYCLE_EVENTS.append("resource.close")
        super().close()


class _RuntimeApplication(ManagedApplication):
    def configure(self, context: ApplicationContext) -> None:
        super().configure(context)
        assert context.binding("bus").context is not None
        _LIFECYCLE_EVENTS.append("application.configure")

    def start(self) -> None:
        super().start()
        _LIFECYCLE_EVENTS.append("application.start")

    def poll(self) -> dict[str, object]:
        return {"status": "completed", "running": False}

    def stop(self) -> None:
        assert self.context is not None
        assert self.context.binding("bus").context is not None
        _LIFECYCLE_EVENTS.append("application.stop")
        super().stop()


def test_public_api_2x_contract_is_preserved() -> None:
    contract_path = (
        Path(__file__).parent / "contracts" / "public_api_2x.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    missing: list[str] = []
    for module_name, symbols in contract.items():
        module = importlib.import_module(module_name)
        missing.extend(
            f"{module_name}.{symbol}"
            for symbol in symbols
            if not hasattr(module, symbol)
        )
    assert missing == []


def test_use_alias_is_accepted_but_canonical_dump_uses_uses(
    tmp_path: Path,
) -> None:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(
        """\
name: compatibility
nodes:
  source:
    use: core.synthetic_source
    count: 1
flow: []
""",
        encoding="utf-8",
    )
    details = load_manifest_details(pipeline)
    assert details.manifest.nodes["source"].uses == "core.synthetic_source"
    assert details.canonical["nodes"]["source"]["uses"] == "core.synthetic_source"
    assert "use" not in details.canonical["nodes"]["source"]
    assert [item.code for item in details.diagnostics] == ["W214"]


def test_compact_application_keeps_flat_parameters_convenient(
    tmp_path: Path,
) -> None:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(
        """\
name: compact-application
runtime: {engine: unified}
sessions:
  ros:
    uses: ros2.session
    distro: jazzy
applications:
  driver:
    uses: ros2.launch
    bindings: {session: ros}
    package: demo_driver
    launch_file: driver.launch.py
nodes: {}
flow: []
""",
        encoding="utf-8",
    )

    manifest = load_manifest_details(pipeline).manifest

    assert manifest.sessions["ros"].parameters == {"distro": "jazzy"}
    assert manifest.applications["driver"].parameters == {
        "package": "demo_driver",
        "launch_file": "driver.launch.py",
    }


def test_canonical_edge_transport_and_legacy_link_migration(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pipeline.yaml"
    source.write_text(
        """\
name: transport-migration
runtime: {engine: unified}
applications:
  publisher: {uses: demo.publisher}
  subscriber: {uses: demo.subscriber}
nodes: {}
flow: []
links:
  - from: publisher.output
    to: subscriber.input
    uses: demo.topic
    parameters: {name: events}
""",
        encoding="utf-8",
    )
    migrated = migrate_manifest(source, write=False)
    manifest = migrated["manifest"]
    assert manifest["links"] == []
    edge = manifest["edges"][0]
    assert edge["transport"]["uses"] == "demo.topic"
    assert edge["transport"]["parameters"] == {"name": "events"}


def test_manifest_schema_is_canonical_and_cli_writes_it(tmp_path: Path) -> None:
    schema = manifest_json_schema()
    encoded = json.dumps(schema)
    assert schema["$schema"].endswith("2020-12/schema")
    assert '"uses"' in encoded

    output = tmp_path / "pipeline.schema.json"
    result = CliRunner().invoke(app, ["schema", "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert json.loads(output.read_text(encoding="utf-8"))["$id"] == schema["$id"]
    packaged = Path(__file__).parents[1] / "src/nodrix/schemas/pipeline.schema.json"
    assert packaged.read_text(encoding="utf-8") == render_manifest_schema()


def test_validate_reports_use_alias_and_strict_rejects_it(tmp_path: Path) -> None:
    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text(
        """\
name: deprecated-use
nodes:
  source:
    use: core.synthetic_source
    count: 1
flow: []
""",
        encoding="utf-8",
    )
    runner = CliRunner()
    compatible = runner.invoke(app, ["validate", str(pipeline), "--json"])
    assert compatible.exit_code == 0, compatible.output
    assert any(item["code"] == "W214" for item in json.loads(compatible.stdout)["issues"])
    strict = runner.invoke(
        app,
        ["validate", str(pipeline), "--strict", "--json"],
    )
    assert strict.exit_code == 1
    assert any(item["code"] == "W214" for item in json.loads(strict.stdout)["issues"])


def test_node_and_application_names_cannot_collide() -> None:
    with pytest.raises(ValueError, match="Node/application names"):
        PipelineManifest.model_validate(
            {
                "metadata": {"name": "collision"},
                "runtime": {"engine": "unified"},
                "applications": {
                    "driver": {"uses": "demo.application"},
                },
                "nodes": {
                    "driver": {"uses": "core.synthetic_source"},
                },
                "edges": [],
            }
        )


def test_transport_neutral_resource_and_application_lifecycle(
    tmp_path: Path,
) -> None:
    resource = ManagedResource({"endpoint": "memory://demo"})
    resource.open(
        ResourceContext(
            name="bus",
            run_dir=tmp_path,
            project_dir=tmp_path,
            runtime_mode="offline",
        )
    )
    assert resource.health()["open"] is True

    application = ManagedApplication({"command": ["demo"]})
    application.configure(
        ApplicationContext(
            name="worker",
            run_dir=tmp_path,
            project_dir=tmp_path,
            runtime_mode="offline",
            bindings={"bus": resource},
        )
    )
    application.start()
    assert application.health()["running"] is True
    application.stop()
    resource.close()
    assert application.lifecycle_state == "stopped"
    assert resource.health()["open"] is False


def test_runtime_supervises_application_and_resource_without_nodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nodrix.runtime_provider_materialization as runtime_provider_materialization

    _LIFECYCLE_EVENTS.clear()
    resource_descriptor = ResourceDescriptor(
        id="demo.bus",
        factory="demo.provider:Bus",
    )
    application_descriptor = ApplicationDescriptor(
        id="demo.worker",
        factory="demo.provider:Worker",
        bindings={"bus": "demo.bus"},
    )
    monkeypatch.setattr(
        runtime_provider_materialization,
        "provider_for_resource",
        lambda *args, **kwargs: (object(), resource_descriptor),
    )
    monkeypatch.setattr(
        runtime_provider_materialization,
        "load_provider_resource",
        lambda *args, **kwargs: _RuntimeResource,
    )
    monkeypatch.setattr(
        runtime_provider_materialization,
        "provider_for_application",
        lambda *args, **kwargs: (object(), application_descriptor),
    )
    monkeypatch.setattr(
        runtime_provider_materialization,
        "load_provider_application",
        lambda *args, **kwargs: _RuntimeApplication,
    )

    manifest = PipelineManifest.model_validate(
        {
            "metadata": {"name": "application-only"},
            "runtime": {
                "engine": "unified",
                "metrics": {"enabled": False},
            },
            "resources": {"bus": {"uses": "demo.bus"}},
            "applications": {
                "worker": {
                    "uses": "demo.worker",
                    "bindings": {"bus": "bus"},
                }
            },
            "nodes": {},
            "edges": [],
        }
    )
    manifest_path = tmp_path / "pipeline.yaml"
    manifest_path.write_text(
        "name: application-only\nnodes: {}\nflow: []\n",
        encoding="utf-8",
    )
    runtime = HybridPipelineRuntime(
        manifest,
        manifest_path,
        run_root=tmp_path / "runs",
    )

    report = runtime.run_sync()

    assert report["status"] == "completed"
    assert report["applications"]["worker"]["running"] is False
    assert _LIFECYCLE_EVENTS == [
        "resource.open",
        "application.configure",
        "application.start",
        "application.stop",
        "resource.close",
    ]


def test_execution_plan_keeps_edge_logical_and_transport_external() -> None:
    manifest = PipelineManifest.model_validate(
        {
            "metadata": {"name": "transport-plan"},
            "runtime": {"engine": "unified"},
            "applications": {
                "publisher": {"uses": "demo.publisher"},
                "subscriber": {"uses": "demo.subscriber"},
            },
            "nodes": {},
            "edges": [
                {
                    "from": "publisher.events",
                    "to": "subscriber.events",
                    "transport": {
                        "uses": "demo.topic",
                        "parameters": {"topic": "events"},
                    },
                }
            ],
        }
    )

    plan = compile_execution_plan(
        manifest,
        {"engine": "unified", "nodes": {}, "edges": []},
    )

    assert plan["topological_order"] == []
    assert plan["edges"][0]["data_plane"] == "external"
    assert plan["edges"][0]["transport"]["uses"] == "demo.topic"
    assert plan["summary"]["planned_copies"] == 0


def test_core_boundary_contracts_do_not_import_ros() -> None:
    core = Path(__file__).parents[1] / "src/nodrix"
    for relative in (
        "integration.py",
        "manifest_model.py",
        "provider_api.py",
    ):
        assert "ros2" not in (core / relative).read_text(encoding="utf-8").lower()
