import json
from importlib.resources import files

from nodrix import ProviderManifest
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
    assert {template.id for template in manifest.templates} >= {
        "ros2",
        "ros2-fast-livo2",
    }
