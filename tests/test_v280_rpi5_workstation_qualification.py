from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from nodrix.system import (
    ExecutionScope,
    backend_context_for_scope,
    plan_execution_scopes,
    plan_system,
    validate_system,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/render_rpi5_workstation_qualification.py"


def _renderer():
    spec = importlib.util.spec_from_file_location("nodrix_m6_renderer", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_renderer_refuses_plaintext_non_loopback_agent() -> None:
    renderer = _renderer()
    with pytest.raises(ValueError, match="requires mTLS"):
        renderer.build_qualification_system(
            pi_agent_host="192.0.2.10",
            pi_agent_port=7843,
            workstation_data_host="192.0.2.20",
            data_port=7850,
            token_env="NODRIX_AGENT_TOKEN",
            record_path="artifacts/qualification/result.jsonl",
            count=10,
            interval_ms=20.0,
        )


def test_renderer_builds_two_target_cross_scope_system() -> None:
    renderer = _renderer()
    system = renderer.build_qualification_system(
        pi_agent_host="127.0.0.1",
        pi_agent_port=7843,
        workstation_data_host="127.0.0.1",
        data_port=7850,
        token_env="NODRIX_AGENT_TOKEN",
        record_path="artifacts/qualification/result.jsonl",
        count=10,
        interval_ms=20.0,
    )

    validation = validate_system(system)
    assert validation.valid, validation.diagnostics
    plan = plan_system(system)
    scopes = plan_execution_scopes(plan)

    assert scopes == (
        ExecutionScope(target="rpi5", backend="process"),
        ExecutionScope(target="workstation", backend="local"),
    )
    assert len(plan.links) == 1
    link = plan.links[0]
    assert link.cross_target is True
    assert link.cross_backend is True
    assert link.transport_required is True
    assert link.transport_uses == "tcp"

    pi_context = backend_context_for_scope(plan, scopes[0])
    workstation_context = backend_context_for_scope(plan, scopes[1])
    assert len(pi_context.outbound_links) == 1
    assert not pi_context.inbound_links
    assert len(workstation_context.inbound_links) == 1
    assert not workstation_context.outbound_links

    pi_target = next(target for target in plan.targets if target.name == "rpi5")
    agent = pi_target.properties["agent"]
    assert agent["host"] == "127.0.0.1"
    assert agent["token_env"] == "NODRIX_AGENT_TOKEN"
