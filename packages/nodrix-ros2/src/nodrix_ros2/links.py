from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class RosTopicContract:
    """The part of a ``ros2.topic`` link relevant to one process node."""

    direction: str
    port: str
    peer: str
    topic: str
    message_type: str
    qos: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _endpoint(value: Any, *, field: str) -> tuple[str, str]:
    text = str(value or "").strip()
    node, separator, port = text.partition(".")
    if not separator or not node.strip() or not port.strip():
        raise ValueError(
            f"ros2.topic {field} must use the '<node>.<port>' form"
        )
    return node.strip(), port.strip()


def topic_contracts(
    links: Iterable[Mapping[str, Any]],
    *,
    node_name: str,
) -> tuple[RosTopicContract, ...]:
    result: list[RosTopicContract] = []
    occupied: dict[tuple[str, str], RosTopicContract] = {}
    for link in links:
        if str(link.get("uses", "")).strip() != "ros2.topic":
            continue
        source_node, source_port = _endpoint(link.get("from"), field="from")
        target_node, target_port = _endpoint(link.get("to"), field="to")
        if source_node != node_name and target_node != node_name:
            continue
        parameters = link.get("parameters") or {}
        if not isinstance(parameters, Mapping):
            raise TypeError("ros2.topic parameters must be a mapping")
        topic = str(parameters.get("topic", "")).strip()
        message_type = str(parameters.get("message_type", "")).strip()
        if not topic or not message_type:
            raise ValueError(
                "ros2.topic requires non-empty topic and message_type"
            )
        qos = parameters.get("qos") or {}
        if not isinstance(qos, Mapping):
            raise TypeError("ros2.topic qos must be a mapping")
        if source_node == node_name:
            contract = RosTopicContract(
                direction="output",
                port=source_port,
                peer=f"{target_node}.{target_port}",
                topic=topic,
                message_type=message_type,
                qos=dict(qos),
            )
            _append_contract(result, occupied, contract)
        if target_node == node_name:
            contract = RosTopicContract(
                direction="input",
                port=target_port,
                peer=f"{source_node}.{source_port}",
                topic=topic,
                message_type=message_type,
                qos=dict(qos),
            )
            _append_contract(result, occupied, contract)
    return tuple(result)


def _append_contract(
    result: list[RosTopicContract],
    occupied: dict[tuple[str, str], RosTopicContract],
    contract: RosTopicContract,
) -> None:
    key = (contract.direction, contract.port)
    previous = occupied.get(key)
    if previous is not None and (
        previous.topic != contract.topic
        or previous.message_type != contract.message_type
    ):
        raise ValueError(
            f"Conflicting ros2.topic links for {contract.direction} port "
            f"{contract.port!r}"
        )
    if previous is None:
        occupied[key] = contract
        result.append(contract)


def apply_topic_contracts(
    parameters: Mapping[str, Any],
    *,
    process_kind: str,
    contracts: Iterable[RosTopicContract],
) -> dict[str, Any]:
    """Compile logical links into CLI remaps or explicit launch arguments."""

    effective = dict(parameters)
    contract_items = tuple(contracts)
    if process_kind in {"ros2.node", "ros2.rviz"}:
        remappings = dict(effective.get("remappings") or {})
        for contract in contract_items:
            remappings.setdefault(contract.port, contract.topic)
        if remappings:
            effective["remappings"] = remappings
    elif process_kind == "ros2.launch":
        port_arguments = effective.get("ros_port_arguments") or {}
        if not isinstance(port_arguments, Mapping):
            raise TypeError("ros_port_arguments must be a mapping")
        arguments = dict(effective.get("arguments") or {})
        for contract in contract_items:
            argument = port_arguments.get(contract.port)
            if argument:
                arguments.setdefault(str(argument), contract.topic)
        if arguments:
            effective["arguments"] = arguments
    return effective


__all__ = ["RosTopicContract", "apply_topic_contracts", "topic_contracts"]
