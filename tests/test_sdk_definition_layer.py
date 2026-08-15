from __future__ import annotations

from dataclasses import dataclass

from nodrix.sdk import MessageDefinition, NodeDefinition, ResourceDefinition
from nodrix.simplified_sdk import ComponentSpec, ParameterSpec
from plyctl import Message, message, node, resource


@message(namespace="definition_layer")
@dataclass(frozen=True)
class Packet:
    value: int


def test_message_decorator_attaches_neutral_definition() -> None:
    definition = Packet.__plyctl_definition__
    assert isinstance(definition, MessageDefinition)
    assert definition.type_id == "definition_layer.packet/v1"
    assert definition.version == 1
    assert definition.python_type is Packet


def test_node_decorator_lowers_definition_through_legacy_adapter() -> None:
    @node
    def echo(packet: Packet, gain: int = 2) -> Packet:
        return Packet(packet.value * gain)

    definition = echo.__plyctl_definition__
    assert isinstance(definition, NodeDefinition)
    assert echo.__plyctl_component_spec__ is definition
    assert ComponentSpec is NodeDefinition
    assert ParameterSpec.__name__ == "ParameterDefinition"
    assert [item.name for item in definition.inputs] == ["packet"]
    assert [item.name for item in definition.outputs] == ["output"]
    assert [item.name for item in definition.parameters] == ["gain"]

    instance = echo({"gain": 3})
    result = instance.process(
        {"packet": Message(payload=Packet(4), type="definition_layer.packet/v1")}
    )
    assert result is not None
    assert result["output"].payload == Packet(12)


def test_resource_decorator_attaches_neutral_definition() -> None:
    @resource
    def cache(capacity: int = 4):
        yield {"capacity": capacity}

    definition = cache.__plyctl_definition__
    assert isinstance(definition, ResourceDefinition)
    assert cache.__plyctl_component_spec__ is definition
    assert [item.name for item in definition.parameters] == ["capacity"]
