from __future__ import annotations

import nodrix
import plyctl


def test_transport_runtime_is_public_on_nodrix_and_plyctl() -> None:
    assert "tcp" in nodrix.registered_transport_runtimes()
    assert nodrix.TransportRuntimeAdapter is plyctl.TransportRuntimeAdapter
    assert nodrix.TransportLocalBackend is plyctl.TransportLocalBackend
    assert nodrix.TransportProcessBackend is plyctl.TransportProcessBackend
    assert nodrix.transport_runtime("tcp") is plyctl.transport_runtime("tcp")
