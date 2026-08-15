import json
from importlib.resources import files

from nodrix import ProviderManifest
from nodrix_spatial_ros2.provider import provider


def test_provider_runtime_matches_metadata() -> None:
    document = json.loads(
        files("nodrix_spatial_ros2")
        .joinpath("nodrix-provider.json")
        .read_text(encoding="utf-8")
    )
    manifest = ProviderManifest.from_dict(document)
    runtime = provider()
    assert runtime.provider_id == manifest.metadata.id
    assert set(runtime.nodes) == {node.id for node in manifest.nodes}
    assert not runtime.sessions


def test_spatial_bridge_requires_platform_and_domain_features() -> None:
    document = json.loads(
        files("nodrix_spatial_ros2")
        .joinpath("nodrix-provider.json")
        .read_text(encoding="utf-8")
    )
    manifest = ProviderManifest.from_dict(document)
    assert set(manifest.metadata.requires_features) == {
        "platform.ros2",
        "domain.spatial.contracts",
    }
