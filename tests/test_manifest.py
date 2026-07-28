from pathlib import Path

from nodrix.manifest import load_manifest


def test_load_quickstart_manifest():
    path = Path(__file__).parents[1] / "examples" / "quickstart" / "pipeline.yaml"
    manifest = load_manifest(path)
    assert manifest.metadata.name == "quickstart"
    assert len(manifest.nodes) == 4
    assert len(manifest.edges) == 3
