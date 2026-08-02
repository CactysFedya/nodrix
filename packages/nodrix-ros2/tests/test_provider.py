import json
from importlib.resources import files
from pathlib import Path

import pytest

from nodrix import ProviderManifest
from nodrix.manifest import load_manifest_details
from nodrix_ros2.provider import provider


def test_provider_runtime_matches_metadata() -> None:
    document = json.loads(
        files("nodrix_ros2")
        .joinpath("nodrix-provider.json")
        .read_text(encoding="utf-8")
    )
    manifest = ProviderManifest.from_dict(document)
    runtime = provider()
    assert runtime.provider_id == manifest.metadata.id
    assert set(runtime.nodes) == {node.id for node in manifest.nodes}
    assert set(runtime.probes) == {probe.id for probe in manifest.probes}
    assert set(runtime.sessions) == {
        session.id for session in manifest.sessions
    }
    assert set(runtime.applications) == {
        application.id for application in manifest.applications
    }
    assert {transport.id for transport in manifest.transports} == {
        "ros2.topic",
    }
    assert {template.id for template in manifest.templates} >= {
        "ros2",
        "ros2-fast-livo2",
    }


@pytest.mark.parametrize("template", ["ros2", "ros2-fast-livo2"])
def test_provider_templates_are_canonical_v2(template: str) -> None:
    pipeline = Path(
        str(
            files("nodrix_ros2")
            .joinpath("templates")
            .joinpath(template)
            .joinpath("pipeline.yaml")
        )
    )

    details = load_manifest_details(pipeline, expand_env=False)

    assert details.manifest.api_version == "plyctl.dev/v2"
    assert details.manifest.applications
    assert all(edge.transport is not None for edge in details.manifest.edges)
    assert details.diagnostics == ()
