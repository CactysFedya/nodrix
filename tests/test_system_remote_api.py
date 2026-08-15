from __future__ import annotations

import nodrix
import plyctl


def test_remote_target_api_is_public_on_nodrix_and_plyctl() -> None:
    assert nodrix.REMOTE_AGENT_PROTOCOL == "nodrix.remote-agent/v1"
    assert nodrix.RemoteAgentClient is plyctl.RemoteAgentClient
    assert nodrix.RemoteAgentEndpoint is plyctl.RemoteAgentEndpoint
    assert nodrix.RemoteAgentServer is plyctl.RemoteAgentServer
    assert nodrix.RemoteProcessBackend is plyctl.RemoteProcessBackend
