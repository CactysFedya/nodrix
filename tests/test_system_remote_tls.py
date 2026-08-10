from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import pytest

from nodrix.system import (
    BackendExecutionState,
    ExecutionScope,
    Graph,
    NodeInstance,
    RemoteAgentEndpoint,
    RemoteAgentError,
    RemoteAgentTLSClientConfig,
    RemoteAgentTLSServerConfig,
    RemoteProcessBackend,
    SystemModel,
    SystemOrchestrator,
    TLSRemoteAgentClient,
    TLSRemoteAgentServer,
    Target,
    backend_context_for_scope,
    plan_execution_scopes,
    plan_system,
)


TOKEN_ENV = "NODRIX_TEST_MTLS_AGENT_TOKEN"


def _write_key(path: Path, key) -> None:
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _new_ca(tmp_path: Path, name: str) -> tuple[object, x509.Certificate, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / f"{name}.ca.pem"
    _write_cert(cert_path, cert)
    return key, cert, cert_path


def _leaf_cert(
    tmp_path: Path,
    *,
    name: str,
    ca_key,
    ca_cert: x509.Certificate,
    server: bool,
) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage(
                [
                    ExtendedKeyUsageOID.SERVER_AUTH
                    if server
                    else ExtendedKeyUsageOID.CLIENT_AUTH
                ]
            ),
            critical=False,
        )
    )
    if server:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
    cert = builder.sign(ca_key, hashes.SHA256())
    cert_path = tmp_path / f"{name}.cert.pem"
    key_path = tmp_path / f"{name}.key.pem"
    _write_cert(cert_path, cert)
    _write_key(key_path, key)
    return cert_path, key_path


def _credentials(tmp_path: Path) -> dict[str, Path]:
    ca_key, ca_cert, ca_file = _new_ca(tmp_path, "nodrix-test")
    server_cert, server_key = _leaf_cert(
        tmp_path,
        name="server",
        ca_key=ca_key,
        ca_cert=ca_cert,
        server=True,
    )
    client_cert, client_key = _leaf_cert(
        tmp_path,
        name="client",
        ca_key=ca_key,
        ca_cert=ca_cert,
        server=False,
    )
    bad_ca_key, bad_ca_cert, _bad_ca_file = _new_ca(tmp_path, "foreign-test")
    bad_client_cert, bad_client_key = _leaf_cert(
        tmp_path,
        name="foreign-client",
        ca_key=bad_ca_key,
        ca_cert=bad_ca_cert,
        server=False,
    )
    return {
        "ca": ca_file,
        "server_cert": server_cert,
        "server_key": server_key,
        "client_cert": client_cert,
        "client_key": client_key,
        "bad_client_cert": bad_client_cert,
        "bad_client_key": bad_client_key,
    }


def _server_tls(creds: dict[str, Path]) -> RemoteAgentTLSServerConfig:
    return RemoteAgentTLSServerConfig(
        cert_file=creds["server_cert"],
        key_file=creds["server_key"],
        ca_file=creds["ca"],
    )


def _client_tls(
    creds: dict[str, Path],
    *,
    foreign: bool = False,
) -> RemoteAgentTLSClientConfig:
    return RemoteAgentTLSClientConfig(
        ca_file=creds["ca"],
        cert_file=(
            creds["bad_client_cert"] if foreign else creds["client_cert"]
        ),
        key_file=creds["bad_client_key"] if foreign else creds["client_key"],
        server_name="localhost",
    )


def _remote_tls_plan(
    *,
    host: str,
    port: int,
    output: Path,
    creds: dict[str, Path] | None,
) -> object:
    agent: dict[str, object] = {
        "host": host,
        "port": port,
        "token_env": TOKEN_ENV,
    }
    if creds is not None:
        agent["tls"] = {
            "ca_file": str(creds["ca"]),
            "cert_file": str(creds["client_cert"]),
            "key_file": str(creds["client_key"]),
            "server_name": "localhost",
        }
    return plan_system(
        SystemModel(
            name="remote-mtls-system",
            targets=(
                Target(
                    name="robot",
                    kind="host",
                    properties={"backend": "process", "agent": agent},
                ),
            ),
            graphs=(
                Graph(
                    name="main",
                    nodes=(
                        NodeInstance(
                            name="source",
                            uses="core.synthetic_source",
                            target="robot",
                            parameters={
                                "count": 2,
                                "payload": {"kind": "remote-mtls"},
                            },
                        ),
                        NodeInstance(
                            name="sink",
                            uses="sink.jsonl",
                            target="robot",
                            parameters={"path": str(output)},
                        ),
                    ),
                    connections=(
                        {"from": "source.output", "to": "sink.input"},
                    ),
                ),
            ),
        )
    )


def test_mtls_agent_accepts_trusted_client_on_non_loopback_listener(
    tmp_path: Path,
) -> None:
    creds = _credentials(tmp_path)
    with TLSRemoteAgentServer(
        host="0.0.0.0",
        port=0,
        token="mtls-token",
        working_directory=tmp_path / "agent",
        tls=_server_tls(creds),
    ) as server:
        _host, port = server.address
        client = TLSRemoteAgentClient(
            RemoteAgentEndpoint(
                host="127.0.0.1",
                port=port,
                token="mtls-token",
            ),
            _client_tls(creds),
        )
        response = client.ping()

    assert response["protocol"] == "nodrix.remote-agent/v1"
    assert "process" in response["backends"]


def test_mtls_agent_rejects_untrusted_client_certificate(tmp_path: Path) -> None:
    creds = _credentials(tmp_path)
    with TLSRemoteAgentServer(
        host="127.0.0.1",
        port=0,
        token="mtls-token",
        working_directory=tmp_path / "agent",
        tls=_server_tls(creds),
    ) as server:
        host, port = server.address
        client = TLSRemoteAgentClient(
            RemoteAgentEndpoint(host=host, port=port, token="mtls-token"),
            _client_tls(creds, foreign=True),
        )
        with pytest.raises(RemoteAgentError, match="AGENT503"):
            client.ping()


def test_remote_backend_rejects_non_loopback_without_tls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(TOKEN_ENV, "token")
    plan = _remote_tls_plan(
        host="192.0.2.10",
        port=7843,
        output=tmp_path / "never.jsonl",
        creds=None,
    )
    scope = plan_execution_scopes(plan)[0]
    context = backend_context_for_scope(plan, scope)
    report = RemoteProcessBackend(working_directory=tmp_path).validate(context)

    assert not report.valid
    assert any(item.code == "REMOTE104" for item in report.errors)


def test_remote_backend_accepts_non_loopback_with_mtls_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    creds = _credentials(tmp_path)
    monkeypatch.setenv(TOKEN_ENV, "token")
    plan = _remote_tls_plan(
        host="192.0.2.10",
        port=7843,
        output=tmp_path / "never.jsonl",
        creds=creds,
    )
    scope = plan_execution_scopes(plan)[0]
    context = backend_context_for_scope(plan, scope)
    report = RemoteProcessBackend(working_directory=tmp_path).validate(context)

    assert report.valid, report.diagnostics


def test_remote_process_scope_completes_over_mtls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    creds = _credentials(tmp_path)
    token = "remote-mtls-token"
    monkeypatch.setenv(TOKEN_ENV, token)
    output = tmp_path / "remote-mtls.jsonl"

    with TLSRemoteAgentServer(
        host="127.0.0.1",
        port=0,
        token=token,
        working_directory=tmp_path / "agent-work",
        run_root=tmp_path / "agent-runs",
        tls=_server_tls(creds),
    ) as server:
        host, port = server.address
        plan = _remote_tls_plan(
            host=host,
            port=port,
            output=output,
            creds=creds,
        )
        scope = plan_execution_scopes(plan)[0]
        assert scope == ExecutionScope(target="robot", backend="process")
        orchestrator = SystemOrchestrator(
            {scope: RemoteProcessBackend(working_directory=tmp_path)}
        )
        validation = orchestrator.validate_plan(plan)
        assert validation.valid, validation.diagnostics
        prepared = orchestrator.prepare_plan(plan)
        assert prepared.scopes[0].prepared.metadata["agent_tls"] is True
        handle = orchestrator.start(prepared)

        deadline = time.monotonic() + 15.0
        status = orchestrator.inspect(handle)
        while not status.terminal and time.monotonic() < deadline:
            time.sleep(0.05)
            status = orchestrator.inspect(handle)

        assert status.state is BackendExecutionState.COMPLETED, status
        assert status.scopes[0].status.details["remote"] is True

    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 2
    assert all(record["payload"]["kind"] == "remote-mtls" for record in records)
