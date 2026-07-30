from __future__ import annotations

import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess

import pytest

import nodrix
from nodrix.discovery import DiscoveryAdvertiser
from nodrix.manifest import PipelineManifest
from nodrix.messages import Message
from nodrix.streams import StreamClient, StreamServer, server_tls_context
from nodrix.validation import validate_production


def _certificate(
    tmp_path: Path,
    *,
    include_ip: bool = True,
) -> tuple[Path, Path]:
    executable = shutil.which("openssl")
    if executable is None:
        pytest.skip("OpenSSL command is unavailable")
    certificate = tmp_path / "server.crt"
    private_key = tmp_path / "server.key"
    completed = subprocess.run(
        [
            executable,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            (
                "subjectAltName=DNS:localhost,IP:127.0.0.1"
                if include_ip
                else "subjectAltName=DNS:localhost"
            ),
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        pytest.skip(f"OpenSSL cannot create a test certificate: {completed.stderr}")
    return certificate, private_key


def _manifest(*, tls: dict[str, object] | None = None) -> PipelineManifest:
    return PipelineManifest.model_validate(
        {
            "metadata": {"name": "secure-remote"},
            "nodes": {"source": {"uses": "core.counter", "parameters": {"count": 1}}},
            "edges": [],
            "streams": {
                "bind_host": "0.0.0.0",
                "exports": [{"name": "/events", "from": "source.output"}],
                "tls": tls or {},
            },
        }
    )


def test_v180_version() -> None:
    assert nodrix.__version__ == "2.1.0"


def test_tls_stream_round_trip(tmp_path: Path) -> None:
    certificate, private_key = _certificate(tmp_path)
    context = server_tls_context(
        certificate=str(certificate),
        private_key=str(private_key),
    )
    server = StreamServer(host="127.0.0.1", tls_context=context)
    server.register("/secure", "core.object")
    server.start()
    client = StreamClient(
        f"nodrix+tls://localhost:{server.port}/secure",
        ca_file=str(certificate),
    )
    try:
        client.connect()
        server.publish("/secure", Message("core.object", {"encrypted": True}, sequence=1))
        received = client.receive()
        assert received.payload == {"encrypted": True}
        assert server.report()["/secure"]["transport"] == "tls"
    finally:
        client.close()
        server.close()


def test_tls_verification_cannot_be_disabled(tmp_path: Path) -> None:
    certificate, private_key = _certificate(tmp_path)
    server = StreamServer(
        host="127.0.0.1",
        tls_context=server_tls_context(
            certificate=str(certificate),
            private_key=str(private_key),
        ),
    )
    server.register("/secure", "core.object")
    server.start()
    client = StreamClient(f"nodrix+tls://localhost:{server.port}/secure")
    try:
        with pytest.raises(ssl.SSLCertVerificationError):
            client.connect()
    finally:
        client.close()
        server.close()


def test_tls_rejects_hostname_mismatch(tmp_path: Path) -> None:
    certificate, private_key = _certificate(
        tmp_path,
        include_ip=False,
    )
    server = StreamServer(
        host="127.0.0.1",
        tls_context=server_tls_context(
            certificate=str(certificate),
            private_key=str(private_key),
        ),
    )
    server.register("/secure", "core.object")
    server.start()
    client = StreamClient(
        f"nodrix+tls://127.0.0.1:{server.port}/secure",
        ca_file=str(certificate),
    )
    try:
        with pytest.raises(ssl.SSLCertVerificationError):
            client.connect()
    finally:
        client.close()
        server.close()


def test_reconnect_attempts_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    server = StreamServer(host="127.0.0.1")
    server.register("/events", "core.object")
    server.start()
    original = socket.create_connection
    attempts = 0

    def flaky(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionRefusedError("fault injection")
        return original(*args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", flaky)
    client = StreamClient(
        f"nodrix://127.0.0.1:{server.port}/events",
        reconnect_attempts=2,
        reconnect_backoff=0,
        reconnect_max_backoff=0,
    )
    try:
        client.connect()
        assert attempts == 3
        assert client.reconnects == 2
    finally:
        client.close()
        server.close()


def test_discovery_advertises_tls_scheme() -> None:
    advertiser = DiscoveryAdvertiser(
        pipeline="secure",
        endpoint_port=7420,
        endpoint_scheme="nodrix+tls",
        streams=lambda: [],
    )
    message = json.loads(advertiser._advertisement())
    assert message["endpoint"]["scheme"] == "nodrix+tls"


def test_tls_manifest_and_production_validation() -> None:
    with pytest.raises(ValueError, match="certificate"):
        _manifest(tls={"enabled": True})
    insecure = _manifest()
    issues = validate_production(insecure, {"edges": []}, strict=True)
    assert any(issue.code == "S104" and issue.severity == "error" for issue in issues)
    secure = _manifest(
        tls={
            "enabled": True,
            "certificate": "server.crt",
            "private_key": "server.key",
        }
    )
    issues = validate_production(secure, {"edges": []}, strict=True)
    assert not any(issue.code == "S104" for issue in issues)
