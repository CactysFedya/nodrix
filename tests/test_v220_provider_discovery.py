from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import uuid

import pytest

import nodrix.providers as provider_module
from nodrix.provider_api import PROVIDER_SCHEMA
from nodrix.providers import discover_providers, provider_for_node


def _editable_provider(
    root: Path,
    *,
    provider_id: str,
    node_id: str,
) -> None:
    package_name = f"editable_provider_{uuid.uuid4().hex}"
    package = root / package_name
    package.mkdir()
    marker = root / f"{package_name}.imported"
    (package / "__init__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (package / "provider.py").write_text(
        "class ExampleNode: pass\n"
        "def provider(): return None\n",
        encoding="utf-8",
    )
    document = {
        "schema": PROVIDER_SCHEMA,
        "metadata": {
            "id": provider_id,
            "name": "Editable Provider",
            "version": "0.1.0",
            "provider_api": "1",
            "requires_nodrix": ">=2.1,<3",
            "features": [node_id],
            "requires_features": [],
        },
        "nodes": [
            {
                "id": node_id,
                "factory": f"{package_name}.provider:ExampleNode",
                "inputs": {},
                "outputs": {"output": "core.any"},
                "optional_inputs": [],
                "features": [],
            }
        ],
        "probes": [],
        "templates": [],
    }
    (package / "nodrix-provider.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )

    # Simulate duplicate metadata left by editable setuptools installs.
    for metadata_suffix in ("dist-info", "egg-info"):
        metadata = root / f"editable_provider-0.1.0.{metadata_suffix}"
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            "Metadata-Version: 2.3\n"
            "Name: editable-provider\n"
            "Version: 0.1.0\n",
            encoding="utf-8",
        )
        (metadata / "entry_points.txt").write_text(
            "[nodrix.providers]\n"
            f"{provider_id} = {package_name}.provider:provider\n",
            encoding="utf-8",
        )
        (metadata / "direct_url.json").write_text(
            json.dumps(
                {
                    "url": root.as_uri(),
                    "dir_info": {"editable": True},
                }
            ),
            encoding="utf-8",
        )
        (metadata / "RECORD").write_text(
            f"{metadata.name}/METADATA,,\n"
            f"{metadata.name}/entry_points.txt,,\n"
            f"{metadata.name}/direct_url.json,,\n"
            f"{metadata.name}/RECORD,,\n",
            encoding="utf-8",
        )


def test_editable_metadata_is_found_and_duplicates_are_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _editable_provider(
        tmp_path,
        provider_id="acme.editable",
        node_id="acme.editable_node",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    candidates = discover_providers(
        include_legacy=False,
        paths=[tmp_path],
    )

    assert len(candidates) == 1
    assert candidates[0].id == "acme.editable"
    assert candidates[0].manifest is not None
    assert candidates[0].error is None
    assert not list(tmp_path.glob("*.imported"))


def test_external_provider_replaces_legacy_provider_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _editable_provider(
        tmp_path,
        provider_id="nodrix.ros2",
        node_id="ros2.point_cloud2_source",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    candidates = discover_providers(
        include_legacy=True,
        paths=[tmp_path],
    )
    ros2 = [item for item in candidates if item.id == "nodrix.ros2"]

    assert len(ros2) == 1
    assert ros2[0].internal is False
    assert ros2[0].distribution == "editable-provider"


def test_node_resolver_uses_deduplicated_editable_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _editable_provider(
        tmp_path,
        provider_id="acme.editable",
        node_id="acme.editable_node",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    local = list(importlib.metadata.distributions(path=[str(tmp_path)]))
    monkeypatch.setattr(
        provider_module.importlib.metadata,
        "distributions",
        lambda **_kwargs: list(local),
    )

    resolved = provider_for_node(
        "acme.editable_node",
        include_legacy=False,
    )

    assert resolved is not None
    candidate, descriptor = resolved
    assert candidate.id == "acme.editable"
    assert descriptor.id == "acme.editable_node"
