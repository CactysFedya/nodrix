from __future__ import annotations

from types import SimpleNamespace
import uuid

import nodrix.resources as resources
import nodrix.shared_memory as shared_memory
from nodrix.shared_memory import SharedBufferPool


def test_shared_memory_omits_track_before_python_313(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_shared_memory(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(shared_memory, "SharedMemory", fake_shared_memory)
    monkeypatch.setattr(shared_memory, "sys", SimpleNamespace(version_info=(3, 12, 9)))

    shared_memory._open_shared_memory(name="nodrix-test", create=True, size=64)

    assert calls == [{"name": "nodrix-test", "create": True, "size": 64}]


def test_shared_memory_disables_resource_tracking_on_python_313(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_shared_memory(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(shared_memory, "SharedMemory", fake_shared_memory)
    monkeypatch.setattr(shared_memory, "sys", SimpleNamespace(version_info=(3, 13, 0)))

    shared_memory._open_shared_memory(name="nodrix-test", create=True, size=64)

    assert calls == [
        {"name": "nodrix-test", "create": True, "size": 64, "track": False}
    ]


def test_shared_memory_name_is_portable_and_deterministic() -> None:
    source = "/nodrix/" + ("camera-front-" * 12)
    first = shared_memory._portable_shared_memory_name(source)
    second = shared_memory._portable_shared_memory_name(source)

    assert first == second
    assert first is not None
    assert len(first) <= shared_memory._MAX_PORTABLE_SHM_NAME
    assert "/" not in first


def test_shared_buffer_pool_reuses_block_and_closes_cleanly() -> None:
    pool = SharedBufferPool(
        block_size=64,
        capacity=2,
        name=f"nodrix-test-{uuid.uuid4().hex}",
    )
    try:
        buffer = pool.acquire(16)
        view = buffer.memoryview()
        view[:4] = b"NDRX"
        assert bytes(view[:4]) == b"NDRX"
        view.release()
        buffer.release()

        stats = pool.stats()
        assert stats["available"] == 2
        assert stats["in_use"] == 0
        assert stats["acquires"] == 1
    finally:
        pool.close()


def test_physical_memory_uses_sysconf_when_available(monkeypatch) -> None:
    values = {"SC_PHYS_PAGES": 1024, "SC_PAGE_SIZE": 4096}
    monkeypatch.setattr(resources.os, "sysconf", lambda key: values[key])

    assert resources._physical_memory_total_bytes() == 1024 * 4096


def test_physical_memory_uses_macos_sysctl_fallback(monkeypatch) -> None:
    def failing_sysconf(_key):
        raise OSError("not available")

    monkeypatch.setattr(resources.os, "sysconf", failing_sysconf)
    monkeypatch.setattr(resources, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(
        resources.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="17179869184\n",
        ),
    )

    assert resources._physical_memory_total_bytes() == 17179869184


def test_system_snapshot_without_posix_resource(monkeypatch) -> None:
    monkeypatch.setattr(resources, "_resource", None)
    monkeypatch.delattr(resources.os, "getloadavg")
    monkeypatch.setattr(
        resources,
        "_physical_memory_total_bytes",
        lambda: None,
    )
    monkeypatch.setattr(
        resources.sys,
        "platform",
        "win32",
    )

    snapshot = resources.system_snapshot()

    assert snapshot["cpu_count"] >= 1
    assert snapshot["load_average"] == []
    assert "process_max_rss_bytes" not in snapshot


def test_ps_process_rejects_zombie_and_zero_rss(monkeypatch) -> None:
    monkeypatch.setattr(
        resources.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="Z 0:00.01 0 0\n",
        ),
    )

    assert resources._ps_process(123) is None


def test_ps_process_parses_live_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        resources.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="S+ 0:01.25 64 128\n",
        ),
    )

    assert resources._ps_process(123) == {
        "pid": 123,
        "cpu_time_seconds": 1.25,
        "rss_bytes": 64 * 1024,
        "vms_bytes": 128 * 1024,
        "threads": None,
    }


def test_process_snapshot_uses_windows_api(monkeypatch) -> None:
    expected = {
        "pid": 123,
        "cpu_time_seconds": 0.5,
        "rss_bytes": 4096,
        "vms_bytes": 8192,
        "threads": None,
    }
    monkeypatch.setattr(resources.sys, "platform", "win32")
    monkeypatch.setattr(resources, "_windows_process", lambda pid: expected if pid == 123 else None)

    assert resources.process_snapshot(123) == expected
