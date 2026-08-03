from __future__ import annotations

from typer.testing import CliRunner

import nodrix
import plyctl
import plyctl.manifest as plyctl_manifest
from nodrix.manifest import PipelineManifest
from plyctl.cli import app
from plyctl.provider_api import (
    PLYCTL_PROVIDER_ENTRY_POINT_GROUP,
    PLYCTL_PROVIDER_SCHEMA_V2,
    ProviderManifest,
)


def _v2(api_version: str) -> dict[str, object]:
    return {
        "apiVersion": api_version,
        "kind": "Pipeline",
        "metadata": {"name": "compatibility"},
        "runtime": {"engine": "unified"},
        "nodes": {"source": {"uses": "core.synthetic_source"}},
        "fragments": {},
        "edges": [],
        "streams": {},
        "recording": {},
        "security": {},
        "placement": {},
    }


def test_public_imports_share_contract_identity() -> None:
    assert plyctl.__version__ == nodrix.__version__ == "2.3.0a1"
    assert plyctl.Message is nodrix.Message
    assert plyctl.PipelineManifest is nodrix.PipelineManifest
    assert plyctl_manifest.PipelineManifest is PipelineManifest
    assert plyctl.PlyctlError is nodrix.NodrixError


def test_new_and_legacy_manifest_names_are_both_supported() -> None:
    current = PipelineManifest.model_validate(_v2("plyctl.dev/v2"))
    legacy = PipelineManifest.model_validate(_v2("nodrix.dev/v2"))
    assert current.api_version == "plyctl.dev/v2"
    assert legacy.api_version == "nodrix.dev/v2"


def test_plyctl_provider_schema_and_entry_point_are_public() -> None:
    assert PLYCTL_PROVIDER_ENTRY_POINT_GROUP == "plyctl.providers"
    manifest = ProviderManifest.from_dict(
        {
            "schema": PLYCTL_PROVIDER_SCHEMA_V2,
            "metadata": {
                "id": "example.provider",
                "name": "Example",
                "version": "1.0.0",
                "provider_api": "2",
                "requires_nodrix": ">=2.2,<3",
            },
        }
    )
    assert manifest.schema == "plyctl-provider/2"


def test_cli_uses_new_brand() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == "Plyctl 2.3.0a1"
