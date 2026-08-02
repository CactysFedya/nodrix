from pathlib import Path

import pytest

from nodrix import (
    LinkDescriptor,
    ProviderManifest,
    ProviderMetadata,
    Session,
    SessionContext,
    SessionDescriptor,
    TemplateDescriptor,
)
from nodrix.execution_plan import compile_execution_plan
from nodrix.manifest import PipelineManifest, load_manifest
from nodrix.provider_validation import validate_provider_parameters
from nodrix.providers import ProviderCandidate, create_provider_project
import nodrix.providers as providers_module


def test_existing_yaml_shape_remains_valid() -> None:
    manifest = PipelineManifest.model_validate(
        {
            "metadata": {"name": "legacy-shape"},
            "nodes": {"source": {"uses": "core.synthetic_source"}},
            "edges": [],
        }
    )
    assert manifest.sessions == {}
    assert manifest.links == []


def test_compact_yaml_adds_sessions_bindings_and_external_links(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pipeline.yaml"
    path.write_text(
        """\
name: ros-compact
runtime:
  engine: unified
sessions:
  transport:
    uses: demo.session
nodes:
  source:
    use: core.synthetic_source
    bindings: {session: transport}
  sink:
    use: core.counter_sink
flow:
  - source.output -> sink.input
links:
  - from: source.ros_output
    to: sink.ros_input
    uses: demo.topic
    parameters: {topic: /demo}
""",
        encoding="utf-8",
    )
    manifest = load_manifest(path)
    assert manifest.nodes["source"].bindings == {"session": "transport"}
    assert manifest.sessions["transport"].uses == "demo.session"
    assert manifest.links[0].parameters["topic"] == "/demo"


def test_execution_plan_exposes_external_links_without_a_runtime_queue() -> None:
    manifest = PipelineManifest.model_validate(
        {
            "metadata": {"name": "external"},
            "runtime": {"engine": "unified"},
            "sessions": {"bus": {"uses": "demo.session"}},
            "nodes": {
                "source": {"uses": "core.synthetic_source"},
                "sink": {"uses": "core.counter_sink"},
            },
            "edges": [],
            "links": [
                {
                    "from": "source.events",
                    "to": "sink.events",
                    "uses": "demo.topic",
                    "parameters": {"topic": "/events"},
                }
            ],
        }
    )
    plan = compile_execution_plan(
        manifest,
        {
            "nodes": {
                "source": {"inputs": {}, "outputs": {}},
                "sink": {"inputs": {}, "outputs": {}},
            },
            "edges": [],
        },
    )
    assert plan["links"][0]["data_plane"] == "external"
    assert plan["links"][0]["planned_copies"] == 0


def test_provider_api_2_requires_matching_schema() -> None:
    metadata = ProviderMetadata(
        id="demo.provider",
        name="Demo",
        version="1.0.0",
        provider_api="2",
    )
    with pytest.raises(ValueError, match="requires provider_api"):
        ProviderManifest(metadata=metadata)
    manifest = ProviderManifest(
        schema="nodrix-provider/2",
        metadata=metadata,
        sessions=(SessionDescriptor("demo.session", "demo:Session"),),
        links=(LinkDescriptor("demo.topic"),),
    )
    assert manifest.sessions[0].id == "demo.session"


def test_provider_parameter_schema_rejects_missing_and_wrong_values() -> None:
    schema = {
        "type": "object",
        "required": ["topic", "mode"],
        "properties": {
            "topic": {"type": "string", "minLength": 1},
            "mode": {"enum": ["graph", "sample"]},
        },
        "additionalProperties": False,
    }
    with pytest.raises(ValueError, match="missing required"):
        validate_provider_parameters(schema, {}, location="link")
    with pytest.raises(ValueError, match="must be one of"):
        validate_provider_parameters(
            schema,
            {"topic": "/cloud", "mode": "invalid"},
            location="link",
        )
    validate_provider_parameters(
        schema,
        {"topic": "/cloud", "mode": "graph"},
        location="link",
    )


def test_base_session_clears_context_on_close(tmp_path: Path) -> None:
    session = Session()
    session.open(
        SessionContext(
            name="bus",
            run_dir=tmp_path,
            project_dir=tmp_path,
            runtime_mode="offline",
        )
    )
    assert session.health()["open"] is True
    session.close()
    assert session.health()["open"] is False


def test_provider_template_copy_is_metadata_first_and_rejects_escape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package = tmp_path / "package"
    source = package / "templates" / "demo"
    source.mkdir(parents=True)
    (source / "pipeline.yaml").write_text("name: demo\n", encoding="utf-8")
    manifest = ProviderManifest(
        metadata=ProviderMetadata(
            id="demo.provider",
            name="Demo",
            version="1.0.0",
        ),
        templates=(TemplateDescriptor("demo", "templates/demo"),),
    )
    metadata_path = package / "nodrix-provider.json"
    metadata_path.write_text("{}\n", encoding="utf-8")
    candidate = ProviderCandidate(
        id="demo.provider",
        distribution="demo-provider",
        distribution_version="1.0.0",
        manifest=manifest,
        document=manifest.to_dict(),
        entry_point=None,
        metadata_path=metadata_path,
        signature_path=None,
    )
    monkeypatch.setattr(
        providers_module,
        "provider_for_template",
        lambda *_args, **_kwargs: (candidate, manifest.templates[0]),
    )
    created = create_provider_project(tmp_path / "project", "demo")
    assert [path.name for path in created] == ["pipeline.yaml"]

    unsafe = TemplateDescriptor("demo", "../escape")
    monkeypatch.setattr(
        providers_module,
        "provider_for_template",
        lambda *_args, **_kwargs: (candidate, unsafe),
    )
    with pytest.raises(Exception, match="unsafe source path"):
        create_provider_project(tmp_path / "unsafe", "demo")
