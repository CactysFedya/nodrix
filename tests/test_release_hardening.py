from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import socket
import stat
import struct
import threading
import time
import zipfile

import pytest
import yaml
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.manifest import PipelineManifest
from nodrix.messages import Message
from nodrix.packages import (
    PACKAGE_FORMAT,
    _validate_archive_limits,
    build_package,
    install_package,
    verify_package,
)
from nodrix.recording import NdrxReader, NdrxWriter, RecordingError
from nodrix.streams import StreamClient, StreamServer
from nodrix.validation import validate_production


def _package_manifest(
    *,
    name: str = "hardening-test",
    version: str = "1.0.0",
    nodrix: str = ">=2,<3",
) -> bytes:
    return yaml.safe_dump(
        {
            "format": PACKAGE_FORMAT,
            "name": name,
            "version": version,
            "nodrix": nodrix,
            "abi": 2,
            "platforms": ["any"],
            "hardware": [],
            "sandbox": "in_process",
            "nodes": {
                "identity": {"python": "identity.py:Identity"},
            },
        }
    ).encode("utf-8")


def _write_archive(
    path: Path,
    files: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> Path:
    checksums = {
        item.filename if isinstance(item, zipfile.ZipInfo) else item:
        hashlib.sha256(content).hexdigest()
        for item, content in files
    }
    metadata = {
        "format": PACKAGE_FORMAT,
        "name": "hardening-test",
        "version": "1.0.0",
        "built_with": "2.0.0",
        "checksums": checksums,
    }
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for item, content in files:
            archive.writestr(item, content)
        archive.writestr(
            "NODRIX-PACKAGE.json",
            json.dumps(metadata, sort_keys=True),
        )
    return path


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../escape.py",
        "/absolute.py",
        "directory\\escape.py",
        "C:/drive.py",
        "CON",
        "trailing.",
    ],
)
def test_package_rejects_non_portable_or_escaping_names(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    archive = _write_archive(
        tmp_path / "unsafe.ndpkg",
        [
            ("nodrix.package.yaml", _package_manifest()),
            ("identity.py", b"class Identity: pass\n"),
            (unsafe_name, b"untrusted\n"),
        ],
    )
    with pytest.raises(ValueError, match="Unsafe package"):
        verify_package(archive)


def test_package_rejects_symlink_duplicate_and_case_collision(
    tmp_path: Path,
) -> None:
    symlink = zipfile.ZipInfo("link.py")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive = _write_archive(
        tmp_path / "symlink.ndpkg",
        [
            ("nodrix.package.yaml", _package_manifest()),
            ("identity.py", b"class Identity: pass\n"),
            (symlink, b"../../outside"),
        ],
    )
    with pytest.raises(ValueError, match="symlink"):
        verify_package(archive)

    duplicate = tmp_path / "duplicate.ndpkg"
    metadata = {
        "format": PACKAGE_FORMAT,
        "name": "hardening-test",
        "version": "1.0.0",
        "checksums": {
            "nodrix.package.yaml": hashlib.sha256(
                _package_manifest()
            ).hexdigest(),
        },
    }
    with zipfile.ZipFile(duplicate, "w") as output:
        output.writestr("nodrix.package.yaml", _package_manifest())
        output.writestr("nodrix.package.yaml", _package_manifest())
        output.writestr("NODRIX-PACKAGE.json", json.dumps(metadata))
    with pytest.raises(ValueError, match="duplicate"):
        verify_package(duplicate)

    collision = _write_archive(
        tmp_path / "collision.ndpkg",
        [
            ("nodrix.package.yaml", _package_manifest()),
            ("identity.py", b"class Identity: pass\n"),
            ("IDENTITY.PY", b"class Other: pass\n"),
        ],
    )
    with pytest.raises(ValueError, match="collide"):
        verify_package(collision)


def test_package_archive_resource_limits(tmp_path: Path) -> None:
    path = tmp_path / "limits.zip"
    with zipfile.ZipFile(
        path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as output:
        output.writestr("first.bin", b"A" * 4096)
        output.writestr("second.bin", b"B" * 4096)

    with zipfile.ZipFile(path) as archive:
        with pytest.raises(ValueError, match="too many"):
            _validate_archive_limits(archive, max_files=1)
        with pytest.raises(ValueError, match="too large"):
            _validate_archive_limits(archive, max_member_bytes=1024)
        with pytest.raises(ValueError, match="uncompressed-size"):
            _validate_archive_limits(
                archive,
                max_uncompressed_bytes=5000,
            )
        with pytest.raises(ValueError, match="compression-ratio"):
            _validate_archive_limits(
                archive,
                max_compression_ratio=2,
            )


def test_package_install_is_atomic_immutable_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NODRIX_HOME", str(tmp_path / "home"))
    source = tmp_path / "package"
    source.mkdir()
    (source / "nodrix.package.yaml").write_bytes(_package_manifest())
    (source / "identity.py").write_text(
        "class Identity: pass\n",
        encoding="utf-8",
    )
    archive = build_package(source, tmp_path / "valid.ndpkg")
    installed = install_package(archive)
    target = Path(installed["path"])
    original = (target / "identity.py").read_bytes()
    with pytest.raises(FileExistsError, match="immutable"):
        install_package(archive)
    assert (target / "identity.py").read_bytes() == original
    assert not list(target.parent.glob(".*.install-*"))

    incompatible = tmp_path / "incompatible"
    incompatible.mkdir()
    (incompatible / "nodrix.package.yaml").write_bytes(
        _package_manifest(name="incompatible", nodrix=">=999")
    )
    (incompatible / "identity.py").write_text(
        "class Identity: pass\n",
        encoding="utf-8",
    )
    bad_archive = build_package(
        incompatible,
        tmp_path / "incompatible.ndpkg",
    )
    with pytest.raises(ValueError, match="requires Nodrix"):
        install_package(bad_archive)
    assert not (
        tmp_path / "home/packages/incompatible/1.0.0"
    ).exists()


def _write_recording(path: Path, *, messages: int = 3) -> Path:
    with NdrxWriter(
        path,
        checkpoint_records=1,
        durable=False,
    ) as writer:
        for sequence in range(messages):
            writer.write(
                Message(
                    "core.bytes",
                    bytes([sequence]),
                    sequence=sequence,
                    stream_id="/test",
                )
            )
    return path


def test_ndrx2_limits_and_trailing_sections(tmp_path: Path) -> None:
    recording = _write_recording(tmp_path / "recording.ndrx")
    with pytest.raises(RecordingError, match="file exceeds"):
        NdrxReader(
            recording,
            max_file_bytes=recording.stat().st_size - 1,
        )
    with pytest.raises(RecordingError, match="chunk-count"):
        NdrxReader(recording, max_chunks=2)
    with pytest.raises(RecordingError, match="record-count"):
        NdrxReader(recording, max_records=2)

    trailing = tmp_path / "trailing.ndrx"
    trailing.write_bytes(recording.read_bytes() + b"NDS2duplicate")
    with pytest.raises(RecordingError, match="trailing data"):
        NdrxReader(trailing)


def test_ndrx2_mutation_fuzz_is_bounded_and_typed(tmp_path: Path) -> None:
    valid = _write_recording(tmp_path / "seed.ndrx", messages=2).read_bytes()
    rng = random.Random(200)
    for case in range(64):
        mutated = bytearray(valid)
        for _ in range(1 + case % 4):
            position = rng.randrange(len(mutated))
            mutated[position] ^= rng.randrange(1, 256)
        path = tmp_path / f"mutation-{case}.ndrx"
        path.write_bytes(mutated)
        try:
            with NdrxReader(
                path,
                max_file_bytes=2 * 1024 * 1024,
                max_chunks=100,
                max_records=100,
                max_streams=100,
            ) as reader:
                list(reader.iter_messages(limit=100))
        except RecordingError:
            pass


def test_reconnect_budget_is_global_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreamClient(
        "nodrix://127.0.0.1:65530/test",
        reconnect_attempts_per_disconnect=2,
        reconnect_max_total_attempts=2,
        reconnect_backoff=0,
    )

    def unavailable(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(socket, "create_connection", unavailable)
    with pytest.raises(OSError, match="offline"):
        client.connect(_reconnect=True)
    assert client.report()["reconnect_attempts_total"] == 2
    with pytest.raises(ConnectionError, match="budget exhausted"):
        client.connect(_reconnect=True)
    assert client.report()["state"] == "budget_exhausted"


def test_reconnect_stable_reset_and_jitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreamClient(
        "nodrix://127.0.0.1:65530/test",
        reconnect_attempts_per_disconnect=2,
        reconnect_max_total_attempts=4,
        reconnect_backoff=2,
        reconnect_max_backoff=2,
        reconnect_reset_after_stable_seconds=0.01,
        reconnect_jitter=0.25,
    )
    client._reconnect_attempt_times.extend(
        [time.monotonic(), time.monotonic()]
    )
    client._connected_since = time.monotonic() - 1
    client._state = "degraded"
    report = client.report()
    assert report["state"] == "connected"
    assert report["reconnect_budget_remaining"] == 4

    delays: list[float] = []

    class EventProbe:
        def is_set(self) -> bool:
            return False

        def wait(self, delay: float) -> bool:
            delays.append(delay)
            return False

    client._shutdown = EventProbe()  # type: ignore[assignment]
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )
    monkeypatch.setattr("nodrix.streams.random.uniform", lambda _a, _b: 1.25)
    with pytest.raises(OSError, match="offline"):
        client.connect(_reconnect=True)
    assert delays == [2.5]


def test_shutdown_interrupts_reconnect_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = StreamClient(
        "nodrix://127.0.0.1:65530/test",
        reconnect_attempts_per_disconnect=10,
        reconnect_max_total_attempts=20,
        reconnect_backoff=10,
        reconnect_max_backoff=10,
        reconnect_jitter=0,
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )
    errors: list[BaseException] = []

    def connect() -> None:
        try:
            client.connect(_reconnect=True)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=connect)
    started = time.monotonic()
    worker.start()
    deadline = started + 2
    while (
        client.report()["reconnect_attempts_total"] == 0
        and time.monotonic() < deadline
    ):
        time.sleep(0.001)
    client.close()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert time.monotonic() - started < 1.5
    assert any(isinstance(error, ConnectionAbortedError) for error in errors)


def test_handshake_rejects_oversized_and_non_object_json() -> None:
    receiver, sender = socket.socketpair()
    try:
        sender.sendall(struct.pack("!I", 1025))
        with pytest.raises(ValueError, match="handshake length"):
            StreamServer._receive_json(receiver, max_handshake_bytes=1024)
    finally:
        receiver.close()
        sender.close()

    receiver, sender = socket.socketpair()
    try:
        payload = b'["not","an","object"]'
        sender.sendall(struct.pack("!I", len(payload)) + payload)
        with pytest.raises(ValueError, match="JSON object"):
            StreamServer._receive_json(receiver)
    finally:
        receiver.close()
        sender.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission test")
def test_production_rejects_world_writable_native_plugin(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "plugin.so"
    plugin.write_bytes(b"not loaded by static validation")
    plugin.chmod(0o666)
    manifest = PipelineManifest.model_validate(
        {
            "apiVersion": "nodrix.dev/v2",
            "kind": "Pipeline",
            "metadata": {"name": "native-security"},
            "runtime": {"engine": "native"},
            "nodes": {
                "plugin": {
                    "uses": f"native:{plugin}#demo.source",
                    "health": {"timeout_ms": 1000},
                }
            },
            "fragments": {},
            "edges": [],
            "streams": {},
            "recording": {},
            "security": {
                "native_plugin_allowlist": [str(tmp_path)],
            },
            "placement": {},
        }
    )
    codes = {
        issue.code
        for issue in validate_production(
            manifest,
            {"edges": []},
            strict=True,
            production=True,
        )
    }
    assert "P509" in codes
    plugin.chmod(0o644)
    codes = {
        issue.code
        for issue in validate_production(
            manifest,
            {"edges": []},
            strict=True,
            production=True,
        )
    }
    assert not {"P506", "P507", "P508", "P509"} & codes


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission test")
def test_cli_production_preflight_rejects_plugin_before_dlopen(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "not-a-library.so"
    plugin.write_bytes(b"this must never reach the dynamic loader")
    plugin.chmod(0o666)
    manifest = {
        "apiVersion": "nodrix.dev/v2",
        "kind": "Pipeline",
        "metadata": {"name": "preflight-order"},
        "runtime": {"engine": "native"},
        "nodes": {
            "plugin": {
                "uses": f"native:{plugin}#demo.source",
                "health": {"timeout_ms": 1000},
            }
        },
        "fragments": {},
        "edges": [],
        "streams": {},
        "recording": {},
        "security": {
            "native_plugin_allowlist": [str(tmp_path)],
        },
        "placement": {},
    }
    path = tmp_path / "pipeline.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["validate", str(path), "--production"],
    )
    assert result.exit_code == 1
    assert "P509" in result.output
    assert "before loading plugins" in result.output
    assert "dlopen" not in result.output.lower()
