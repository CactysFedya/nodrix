from __future__ import annotations

import threading
from types import SimpleNamespace

from nodrix.process_host import (
    ProcessNodeProxy,
)


def _probe(
    policy: str,
    *,
    max_restarts: int = 3,
):
    calls = []

    probe = SimpleNamespace(
        _restart_lock=threading.RLock(),
        failure_policy=policy,
        restarts=0,
        max_restarts=max_restarts,
        backoff_ms=0,
    )

    probe._terminate = (
        lambda: calls.append(
            "terminate"
        )
    )

    probe._start_child = (
        lambda: calls.append(
            "start"
        )
    )

    return (
        probe,
        calls,
    )


def test_restart_node_policy_allows_process_restart():
    probe, calls = _probe(
        "restart_node"
    )

    restarted = (
        ProcessNodeProxy._restart(
            probe
        )
    )

    assert restarted is True
    assert probe.restarts == 1

    assert calls == [
        "terminate",
        "start",
    ]


def test_legacy_restart_alias_remains_supported():
    probe, calls = _probe(
        "restart"
    )

    restarted = (
        ProcessNodeProxy._restart(
            probe
        )
    )

    assert restarted is True
    assert probe.restarts == 1

    assert calls == [
        "terminate",
        "start",
    ]


def test_non_restart_policy_does_not_restart_process():
    probe, calls = _probe(
        "stop_execution"
    )

    restarted = (
        ProcessNodeProxy._restart(
            probe
        )
    )

    assert restarted is False
    assert probe.restarts == 0
    assert calls == []


def test_restart_limit_is_still_enforced():
    probe, calls = _probe(
        "restart_node",
        max_restarts=0,
    )

    restarted = (
        ProcessNodeProxy._restart(
            probe
        )
    )

    assert restarted is False
    assert probe.restarts == 0
    assert calls == []
