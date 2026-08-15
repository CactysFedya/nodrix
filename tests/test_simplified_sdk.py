from __future__ import annotations

from dataclasses import dataclass

import pytest

from plyctl import (
    Context,
    Input,
    Message,
    NodeContext,
    Outputs,
    Param,
    Resource,
    ResourceContext,
    SinkNode,
    SourceNode,
    message,
    node,
    resource,
)


@message(namespace="tests")
@dataclass(frozen=True)
class Sample:
    value: int


@message("result/v2", namespace="tests")
@dataclass(frozen=True)
class Result:
    value: int


def test_message_decorator_registers_stable_contract() -> None:
    assert Sample.__plyctl_message_type__ == "tests.sample/v1"
    assert Result.__plyctl_message_type__ == "tests.result/v2"
    assert Result.__plyctl_message_version__ == 2


def test_function_node_infers_ports_and_parameters() -> None:
    @node(name="double")
    def double(sample: Sample, scale: int = 2) -> Result:
        return Result(sample.value * scale)

    assert double.input_types == {"sample": "tests.sample/v1"}
    assert double.output_types == {"output": "tests.result/v2"}

    instance = double({"scale": 3})
    outputs = instance.process({"sample": Message(type="tests.sample/v1", payload=Sample(4))})
    assert outputs is not None
    assert outputs["output"].type == "tests.result/v2"
    assert outputs["output"].payload == Result(12)


def test_input_and_param_markers_override_inference() -> None:
    @node
    def threshold(value: Input[float], limit: Param[float] = 0.5) -> bool:
        return value > limit

    assert threshold.input_types == {"value": "core.float"}
    instance = threshold({"limit": 1.0})
    outputs = instance.process({"value": Message(type="core.float", payload=2.0)})
    assert outputs is not None
    assert outputs["output"].payload is True


def test_source_and_sink_are_inferred_from_signature() -> None:
    @node
    def source(count: int = 2) -> Sample:
        for value in range(count):
            yield Sample(value)

    @node
    def sink(sample: Sample) -> None:
        assert isinstance(sample, Sample)

    assert issubclass(source, SourceNode)
    assert issubclass(sink, SinkNode)
    produced = list(source({"count": 2}).produce())
    assert [item["output"].payload.value for item in produced] == [0, 1]


def test_optional_input_is_marked_optional() -> None:
    @node
    def merge(primary: Sample, secondary: Sample | None = None) -> Result:
        return Result(primary.value + (secondary.value if secondary else 0))

    assert merge.optional_inputs == frozenset({"secondary"})
    outputs = merge().process({"primary": Message(type="tests.sample/v1", payload=Sample(3))})
    assert outputs is not None
    assert outputs["output"].payload == Result(3)


def test_named_multi_output() -> None:
    class Pair(Outputs):
        left: Sample
        right: Result

    @node
    def split(sample: Sample) -> Pair:
        return Pair(left=sample, right=Result(sample.value))

    assert split.output_types == {
        "left": "tests.sample/v1",
        "right": "tests.result/v2",
    }
    outputs = split().process({"sample": Message(type="tests.sample/v1", payload=Sample(8))})
    assert outputs is not None
    assert outputs["left"].payload == Sample(8)
    assert outputs["right"].payload == Result(8)


def test_context_is_injected_only_when_configured(tmp_path) -> None:
    @node
    def inspect_context(sample: Sample, ctx: Context) -> Result:
        return Result(sample.value + int(ctx.name == "ctx-node"))

    instance = inspect_context()
    with pytest.raises(RuntimeError, match="has not been configured"):
        instance.process({"sample": Message(type="tests.sample/v1", payload=Sample(1))})

    instance.configure(
        NodeContext(
            name="ctx-node",
            run_dir=tmp_path,
            project_dir=tmp_path,
            runtime_mode="unified",
        )
    )
    outputs = instance.process({"sample": Message(type="tests.sample/v1", payload=Sample(1))})
    assert outputs is not None
    assert outputs["output"].payload == Result(2)


def test_resource_generator_and_node_injection(tmp_path) -> None:
    events: list[str] = []

    @resource(name="client")
    def client(prefix: str = "value"):
        events.append("open")
        yield {"prefix": prefix}
        events.append("close")

    managed = client({"prefix": "x"})
    managed.open(
        ResourceContext(
            name="client",
            run_dir=tmp_path,
            project_dir=tmp_path,
            runtime_mode="unified",
        )
    )
    assert managed.value == {"prefix": "x"}

    @node
    def use_client(sample: Sample, client: Resource[dict]) -> Result:
        return Result(sample.value + int(client["prefix"] == "x"))

    instance = use_client()
    instance.configure(
        NodeContext(
            name="consumer",
            run_dir=tmp_path,
            project_dir=tmp_path,
            runtime_mode="unified",
            bindings={"client": managed},
        )
    )
    outputs = instance.process({"sample": Message(type="tests.sample/v1", payload=Sample(4))})
    assert outputs is not None
    assert outputs["output"].payload == Result(5)

    managed.close()
    assert events == ["open", "close"]


def test_unknown_and_missing_parameters_fail_early() -> None:
    @node
    def configured(sample: Sample, required: int) -> Result:
        return Result(sample.value + required)

    with pytest.raises(TypeError, match="Missing required parameter"):
        configured()
    with pytest.raises(TypeError, match="Unknown parameter"):
        configured({"typo": 1})
