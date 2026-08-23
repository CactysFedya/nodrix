from __future__ import annotations

import pytest

from nodrix.runtime_transport_binding import (
    RuntimeTransportBinding,
    RuntimeTransportSideBinding,
)


def _transport(
    **overrides,
):
    values = {
        "source": "capture/source.out",
        "target": "mapping/sink.in",
        "uses": "demo.transport",
        "type_id": "demo.frame/v1",
        "parameters": {
            "topic": "/frames",
        },
    }

    values.update(
        overrides
    )

    return RuntimeTransportBinding(
        **values
    )


def test_runtime_transport_binding_preserves_resolved_values():
    binding = _transport()

    assert (
        binding.source
        == "capture/source.out"
    )

    assert (
        binding.target
        == "mapping/sink.in"
    )

    assert (
        binding.uses
        == "demo.transport"
    )

    assert (
        binding.type_id
        == "demo.frame/v1"
    )

    assert dict(
        binding.parameters
    ) == {
        "topic": "/frames",
    }


def test_runtime_transport_parameters_are_immutable_copy():
    parameters = {
        "topic": "/frames",
    }

    binding = _transport(
        parameters=parameters,
    )

    parameters[
        "topic"
    ] = "/changed"

    assert (
        binding.parameters[
            "topic"
        ]
        == "/frames"
    )

    with pytest.raises(
        TypeError,
    ):
        binding.parameters[
            "topic"
        ] = "/other"


@pytest.mark.parametrize(
    "field_name",
    (
        "source",
        "target",
        "uses",
    ),
)
def test_runtime_transport_requires_non_empty_identity_fields(
    field_name,
):
    with pytest.raises(
        ValueError,
        match=field_name,
    ):
        _transport(
            **{
                field_name: "",
            }
        )


def test_runtime_transport_type_id_may_be_absent():
    binding = _transport(
        type_id=None,
    )

    assert (
        binding.type_id
        is None
    )


def test_runtime_transport_rejects_empty_type_id():
    with pytest.raises(
        ValueError,
        match="type_id",
    ):
        _transport(
            type_id="",
        )


def test_runtime_transport_requires_mapping_parameters():
    with pytest.raises(
        TypeError,
        match="parameters",
    ):
        _transport(
            parameters=[],
        )


def test_transport_side_preserves_local_direction():
    transport = _transport()

    side = RuntimeTransportSideBinding(
        transport=transport,
        direction="outbound",
        local_endpoint="capture/source.out",
        remote_endpoint="mapping/sink.in",
    )

    assert (
        side.transport
        is transport
    )

    assert (
        side.direction
        == "outbound"
    )

    assert (
        side.local_endpoint
        == transport.source
    )

    assert (
        side.remote_endpoint
        == transport.target
    )


@pytest.mark.parametrize(
    "direction",
    (
        "",
        "internal",
        "sideways",
    ),
)
def test_transport_side_rejects_unknown_direction(
    direction,
):
    with pytest.raises(
        ValueError,
        match="direction",
    ):
        RuntimeTransportSideBinding(
            transport=_transport(),
            direction=direction,
            local_endpoint="source.out",
            remote_endpoint="sink.in",
        )


@pytest.mark.parametrize(
    "field_name",
    (
        "local_endpoint",
        "remote_endpoint",
    ),
)
def test_transport_side_requires_endpoints(
    field_name,
):
    values = {
        "transport": _transport(),
        "direction": "inbound",
        "local_endpoint": "sink.in",
        "remote_endpoint": "source.out",
    }

    values[
        field_name
    ] = ""

    with pytest.raises(
        ValueError,
        match=field_name,
    ):
        RuntimeTransportSideBinding(
            **values
        )


def test_transport_side_requires_transport_binding():
    with pytest.raises(
        TypeError,
        match="transport",
    ):
        RuntimeTransportSideBinding(
            transport=object(),
            direction="inbound",
            local_endpoint="sink.in",
            remote_endpoint="source.out",
        )
