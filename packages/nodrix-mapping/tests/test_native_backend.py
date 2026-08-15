from __future__ import annotations

import importlib

import pytest


def test_native_extension_is_available_when_built() -> None:
    module = pytest.importorskip(
        "nodrix_mapping._mapping_native",
        reason="native extension was not built for this test environment",
    )
    for name in (
        "create",
        "integrate",
        "snapshot",
        "stats",
        "write_ply_atomic",
    ):
        assert hasattr(module, name)


def test_provider_registers_native_nodes() -> None:
    from nodrix_mapping.provider import provider

    runtime = provider()
    assert set(runtime.nodes) == {
        "mapping.voxel_map",
        "mapping.ply_store",
    }


def test_provider_manifest_declares_native_nodes() -> None:
    import json
    from importlib.resources import files

    document = json.loads(
        files("nodrix_mapping")
        .joinpath("nodrix-provider.json")
        .read_text(encoding="utf-8")
    )
    assert document["metadata"]["version"] == "0.3.0"
    ids = {item["id"] for item in document["nodes"]}
    assert ids == {"mapping.voxel_map", "mapping.ply_store"}
