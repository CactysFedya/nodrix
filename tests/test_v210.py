from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sys
import uuid

import pytest
from typer.testing import CliRunner

from nodrix import (
    Node,
    NodeDescriptor,
    ProbeDescriptor,
    ProviderError,
    ProviderManifest,
    ProviderMetadata,
)
from nodrix.cli import app
from nodrix.doctor import doctor_report
from nodrix.provider_api import PROVIDER_SCHEMA
from nodrix.providers import (
    ProviderPolicy,
    discover_providers,
    load_provider_node,
    reset_provider_cache,
    sign_provider_metadata,
    verify_candidate,
    verify_provider_nodes,
)
from nodrix.registry import load_node_class


runner = CliRunner()


def _canonical(document: dict) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _install_fake_provider(
    root: Path,
    *,
    provider_id: str = "acme.test",
    version: str = "1.0.0",
    requires_features: list[str] | None = None,
    malformed: bool = False,
    signing_key=None,
) -> tuple[Path, Path, dict]:
    suffix = uuid.uuid4().hex
    module_name = f"fake_provider_{suffix}"
    marker = root / f"{module_name}.imported"
    module = root / f"{module_name}.py"
    module.write_text(
        "from pathlib import Path\n"
        "from nodrix import Node\n"
        f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n"
        "class Echo(Node):\n"
        " input_types={'input':'core.any'}\n"
        " output_types={'output':'core.any'}\n"
        " def process(self, inputs): return {'output': inputs['input']}\n"
        "def safe_probe(): return {'status':'ok','provider':'fake'}\n"
        "def deep_probe(): return {'status':'ok','device_opened':True}\n"
        "def provider():\n"
        f" return {{'provider_id':{provider_id!r},"
        f"'nodes':{{'acme.echo':Echo}},"
        f"'probes':{{'{provider_id}.safe':safe_probe,"
        f"'{provider_id}.deep':deep_probe}}}}\n",
        encoding="utf-8",
    )
    dist_info = root / f"acme_test-{version}.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.3\n"
        "Name: acme-test\n"
        f"Version: {version}\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        "[nodrix.providers]\n"
        f"{provider_id} = {module_name}:provider\n",
        encoding="utf-8",
    )
    document = {
        "schema": PROVIDER_SCHEMA,
        "metadata": {
            "id": provider_id,
            "name": "Acme Test Provider",
            "version": version,
            "provider_api": "1",
            "requires_nodrix": ">=2.1,<3",
            "features": ["acme.echo"],
            "requires_features": requires_features or [],
        },
        "nodes": [
            {
                "id": "acme.echo",
                "factory": f"{module_name}:Echo",
                "inputs": {"input": "core.any"},
                "outputs": {"output": "core.any"},
            }
        ],
        "probes": [
            {
                "id": f"{provider_id}.safe",
                "callable": f"{module_name}:safe_probe",
                "depth": "safe",
                "timeout_seconds": 1.0,
            },
            {
                "id": f"{provider_id}.deep",
                "callable": f"{module_name}:deep_probe",
                "depth": "deep",
                "timeout_seconds": 1.0,
                "permissions": ["device"],
            },
        ],
        "templates": [],
    }
    provider_metadata = dist_info / "nodrix-provider.json"
    provider_metadata.write_text(
        "{broken"
        if malformed
        else json.dumps(document, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    files = [
        module.name,
        f"{dist_info.name}/METADATA",
        f"{dist_info.name}/entry_points.txt",
        f"{dist_info.name}/nodrix-provider.json",
    ]
    if signing_key is not None:
        from cryptography.hazmat.primitives import serialization

        public_der = signing_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        signature = {
            "algorithm": "ed25519",
            "key_sha256": hashlib.sha256(public_der).hexdigest(),
            "value": base64.b64encode(
                signing_key.sign(_canonical(document))
            ).decode("ascii"),
        }
        (dist_info / "nodrix-provider.sig").write_text(
            json.dumps(signature),
            encoding="utf-8",
        )
        files.append(f"{dist_info.name}/nodrix-provider.sig")
    files.append(f"{dist_info.name}/RECORD")
    (dist_info / "RECORD").write_text(
        "".join(f"{name},,\n" for name in files),
        encoding="utf-8",
    )
    return marker, provider_metadata, document


@pytest.fixture(autouse=True)
def _clear_provider_cache() -> None:
    reset_provider_cache()
    yield
    reset_provider_cache()


def test_provider_api_validates_descriptors() -> None:
    metadata = ProviderMetadata(
        id="acme.test",
        name="Acme",
        version="1.0.0",
        features=("domain.test",),
    )
    node = NodeDescriptor(
        id="acme.echo",
        factory="acme.nodes:Echo",
        inputs={"input": "core.any"},
        outputs={"output": "core.any"},
        optional_inputs=("input",),
    )
    probe = ProbeDescriptor(
        id="acme.test.safe",
        callable="acme.probes:safe",
    )
    manifest = ProviderManifest(
        metadata=metadata,
        nodes=(node,),
        probes=(probe,),
    )

    assert manifest.to_dict()["schema"] == PROVIDER_SCHEMA
    with pytest.raises(ValueError, match="lowercase dotted identifier"):
        ProviderMetadata(id="Bad Provider", name="Bad", version="1")
    with pytest.raises(ValueError, match="declared input"):
        NodeDescriptor(
            id="acme.bad",
            factory="acme.nodes:Bad",
            optional_inputs=("missing",),
        )


def test_discovery_is_metadata_only_and_node_import_is_lazy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker, _, _ = _install_fake_provider(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    candidates = discover_providers(
        include_legacy=False,
        paths=[tmp_path],
    )

    assert [item.id for item in candidates] == ["acme.test"]
    assert marker.exists() is False
    node_class = load_provider_node("acme.echo")
    assert node_class is not None
    assert issubclass(node_class, Node)
    assert marker.is_file()


def test_registry_uses_external_provider_and_core_survives_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_provider(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    assert load_node_class("acme.echo").__name__ == "Echo"
    monkeypatch.undo()
    reset_provider_cache()
    sys.modules.pop(
        next(
            name
            for name in list(sys.modules)
            if name.startswith("fake_provider_")
        ),
        None,
    )
    assert load_node_class("core.identity").__name__ == "IdentityNode"


def test_unsigned_provider_is_allowed_in_development_and_rejected_in_production(
    tmp_path: Path,
) -> None:
    _install_fake_provider(tmp_path)
    candidate = discover_providers(
        include_legacy=False,
        paths=[tmp_path],
    )[0]

    development = verify_candidate(
        candidate,
        policy=ProviderPolicy(production=False, trust_store=tmp_path / "trust"),
    )
    production = verify_candidate(
        candidate,
        policy=ProviderPolicy(
            production=True,
            trust_store=tmp_path / "trust",
            allowlist=frozenset({"acme.test"}),
        ),
    )

    assert development.status == "unsigned"
    assert development.errors == ()
    assert any("detached signature" in error for error in production.errors)


def test_production_pipeline_verification_rejects_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker, _, _ = _install_fake_provider(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ProviderError, match="detached signature"):
        verify_provider_nodes(
            ["acme.echo"],
            policy=ProviderPolicy(
                production=True,
                trust_store=tmp_path / "trust",
                allowlist=frozenset({"acme.test"}),
            ),
        )

    assert marker.exists() is False


def test_signed_provider_uses_trust_store_and_allowlist(tmp_path: Path) -> None:
    cryptography = pytest.importorskip("cryptography")
    assert cryptography is not None
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    private_key = Ed25519PrivateKey.generate()
    _, metadata_path, document = _install_fake_provider(
        tmp_path,
        signing_key=private_key,
    )
    trust_store = tmp_path / "trust"
    trust_store.mkdir()
    (trust_store / "acme.pem").write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    candidate = discover_providers(
        include_legacy=False,
        paths=[tmp_path],
    )[0]

    result = verify_candidate(
        candidate,
        policy=ProviderPolicy(
            production=True,
            trust_store=trust_store,
            allowlist=frozenset({"acme.test"}),
        ),
    )

    assert result.status == "verified"
    assert result.signed is True
    assert result.trusted is True
    assert result.errors == ()

    document["metadata"]["description"] = "tampered after signing"
    metadata_path.write_text(
        json.dumps(document),
        encoding="utf-8",
    )
    tampered = discover_providers(
        include_legacy=False,
        paths=[tmp_path],
    )[0]
    tampered_result = verify_candidate(
        tampered,
        policy=ProviderPolicy(
            production=True,
            trust_store=trust_store,
            allowlist=frozenset({"acme.test"}),
        ),
    )
    assert any(
        "signature verification failed" in error
        for error in tampered_result.errors
    )


def test_provider_signature_helper_writes_detached_signature(
    tmp_path: Path,
) -> None:
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    private_key = Ed25519PrivateKey.generate()
    _, metadata_path, _ = _install_fake_provider(tmp_path)
    private_path = tmp_path / "private.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    signature_path = sign_provider_metadata(
        metadata_path,
        private_path,
    )
    signature = json.loads(signature_path.read_text(encoding="utf-8"))

    assert signature_path.name == "nodrix-provider.sig"
    assert signature["algorithm"] == "ed25519"
    assert len(signature["key_sha256"]) == 64


def test_corrupt_and_feature_incompatible_providers_are_rejected(
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    _install_fake_provider(broken, malformed=True)
    incompatible = tmp_path / "incompatible"
    incompatible.mkdir()
    _install_fake_provider(
        incompatible,
        provider_id="acme.future",
        requires_features=["backend-api.1"],
    )

    broken_candidate = discover_providers(
        include_legacy=False,
        paths=[broken],
    )[0]
    future_candidate = discover_providers(
        include_legacy=False,
        paths=[incompatible],
    )[0]
    future_verification = verify_candidate(future_candidate)

    assert broken_candidate.manifest is None
    assert broken_candidate.error
    assert future_verification.compatible is False
    assert future_verification.missing_features == ("backend-api.1",)


def test_provider_cli_and_unified_doctor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker, _, _ = _install_fake_provider(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))

    listed = runner.invoke(app, ["provider", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    records = json.loads(listed.output)
    external = next(item for item in records if item["id"] == "acme.test")
    assert external["verification"]["status"] == "unsigned"
    assert marker.exists() is False

    report = doctor_report(provider_id="acme.test")
    assert report["status"] == "ok"
    assert report["providers"][0]["diagnostics"][0]["status"] == "ok"
    assert report["providers"][0]["diagnostics"][1]["status"] == "skipped"
    assert marker.is_file()

    command = runner.invoke(
        app,
        ["doctor", "--provider", "acme.test", "--json"],
    )
    assert command.exit_code == 0, command.output
    assert json.loads(command.output)["schema"] == "nodrix-doctor/1"
