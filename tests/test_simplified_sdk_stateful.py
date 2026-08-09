from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from plyctl import Context, Input, Message, NodeContext, Resource, SourceNode, message, node


@message(namespace="tests_stateful")
@dataclass(frozen=True)
class StatefulSample:
    value: int


@message(namespace="tests_stateful")
@dataclass(frozen=True)
class StatefulResult:
    value: int


def _context(tmp_path, *, bindings=None) -> NodeContext:
    return NodeContext(
        name="stateful",
        run_dir=tmp_path,
        project_dir=tmp_path,
        runtime_mode="unified",
        bindings=bindings or {},
    )


def test_class_node_keeps_state_and_uses_init_for_parameters() -> None:
    @node
    class Accumulator:
        def __init__(self, scale: int = 2):
            self.scale = scale
            self.total = 0

        def process(self, sample: StatefulSample) -> StatefulResult:
            self.total += sample.value * self.scale
            return StatefulResult(self.total)

    assert Accumulator.input_types == {"sample": "tests_stateful.stateful_sample/v1"}
    assert Accumulator.output_types == {"output": "tests_stateful.stateful_result/v1"}
    assert [item.name for item in Accumulator.__plyctl_component_spec__.parameters] == ["scale"]

    instance = Accumulator({"scale": 3})
    first = instance.process(
        {"sample": Message(type="tests_stateful.stateful_sample/v1", payload=StatefulSample(2))}
    )
    second = instance.process(
        {"sample": Message(type="tests_stateful.stateful_sample/v1", payload=StatefulSample(4))}
    )
    assert first is not None and first["output"].payload == StatefulResult(6)
    assert second is not None and second["output"].payload == StatefulResult(18)
    assert instance.implementation is not None


def test_class_node_injects_context_and_resource_into_constructor_and_lifecycle(tmp_path) -> None:
    events: list[str] = []

    @node
    class Consumer:
        def __init__(
            self,
            client: Resource[dict],
            ctx: Context,
            offset: int = 1,
        ):
            self.client = client
            self.created_for = ctx.name
            self.offset = offset

        def start(self, ctx: Context) -> None:
            events.append(f"start:{ctx.name}")

        def process(self, sample: StatefulSample, ctx: Context) -> StatefulResult:
            return StatefulResult(
                sample.value
                + self.offset
                + int(self.client["ready"])
                + int(ctx.name == self.created_for)
            )

        def drain(self, client: Resource[dict]) -> StatefulResult:
            events.append("drain")
            return StatefulResult(int(client["ready"]))

        def stop(self, ctx: Context) -> None:
            events.append(f"stop:{ctx.name}")

        def health(self) -> dict[str, object]:
            return {"client_ready": self.client["ready"]}

    managed = SimpleNamespace(value={"ready": True})
    instance = Consumer({"offset": 4})
    assert instance.implementation is None
    instance.configure(_context(tmp_path, bindings={"client": managed}))
    assert instance.implementation is not None

    instance.start()
    assert instance.lifecycle_state == "running"
    outputs = instance.process(
        {"sample": Message(type="tests_stateful.stateful_sample/v1", payload=StatefulSample(5))}
    )
    assert outputs is not None
    assert outputs["output"].payload == StatefulResult(11)

    drained = instance.drain()
    assert drained is not None
    assert drained["output"].payload == StatefulResult(1)
    assert instance.lifecycle_state == "draining"

    health = instance.health()
    assert health["details"] == {"client_ready": True}

    instance.stop()
    assert instance.lifecycle_state == "stopped"
    assert events == ["start:stateful", "drain", "stop:stateful"]


def test_class_node_async_process_drain_start_and_stop(tmp_path) -> None:
    events: list[str] = []

    @node
    class AsyncAccumulator:
        def __init__(self, scale: int = 2):
            self.scale = scale

        async def start(self, ctx: Context) -> None:
            await asyncio.sleep(0)
            events.append(f"start:{ctx.name}")

        async def process(self, sample: StatefulSample) -> StatefulResult:
            await asyncio.sleep(0)
            return StatefulResult(sample.value * self.scale)

        async def drain(self) -> StatefulResult:
            await asyncio.sleep(0)
            events.append("drain")
            return StatefulResult(-1)

        async def stop(self) -> None:
            await asyncio.sleep(0)
            events.append("stop")

    assert inspect.iscoroutinefunction(AsyncAccumulator.process)
    assert inspect.iscoroutinefunction(AsyncAccumulator.flush)

    async def scenario() -> None:
        instance = AsyncAccumulator({"scale": 5})
        instance.configure(_context(tmp_path))
        await instance.start()
        assert instance.lifecycle_state == "running"
        outputs = await instance.process(
            {"sample": Message(type="tests_stateful.stateful_sample/v1", payload=StatefulSample(3))}
        )
        assert outputs is not None
        assert outputs["output"].payload == StatefulResult(15)
        drained = await instance.drain()
        assert drained is not None
        assert drained["output"].payload == StatefulResult(-1)
        await instance.stop()
        assert instance.lifecycle_state == "stopped"

    asyncio.run(scenario())
    assert events == ["start:stateful", "drain", "stop"]


def test_stateful_generator_source_is_inferred() -> None:
    @node
    class CounterSource:
        def __init__(self, count: int = 3):
            self.count = count

        def process(self) -> StatefulSample:
            for value in range(self.count):
                yield StatefulSample(value)

    assert issubclass(CounterSource, SourceNode)
    produced = list(CounterSource({"count": 2}).produce())
    assert [item["output"].payload for item in produced] == [StatefulSample(0), StatefulSample(1)]


def test_async_function_node_preserves_coroutine_identity() -> None:
    @node
    async def async_double(sample: StatefulSample) -> StatefulResult:
        await asyncio.sleep(0)
        return StatefulResult(sample.value * 2)

    assert inspect.iscoroutinefunction(async_double.process)
    outputs = asyncio.run(
        async_double().process(
            {"sample": Message(type="tests_stateful.stateful_sample/v1", payload=StatefulSample(6))}
        )
    )
    assert outputs is not None
    assert outputs["output"].payload == StatefulResult(12)


def test_class_process_configuration_must_live_in_init() -> None:
    with pytest.raises(TypeError, match="Move configuration to __init__"):
        @node
        class InvalidProcessParameter:
            def process(
                self,
                sample: StatefulSample,
                scale: int = 2,
            ) -> StatefulResult:
                return StatefulResult(sample.value * scale)


def test_class_constructor_rejects_pipeline_input_marker() -> None:
    with pytest.raises(TypeError, match=r"cannot be Input\[T\]"):
        @node
        class InvalidConstructorInput:
            def __init__(self, sample: Input[StatefulSample]):
                self.sample = sample

            def process(self, value: StatefulSample) -> StatefulResult:
                return StatefulResult(value.value)


def test_class_health_must_be_synchronous() -> None:
    with pytest.raises(TypeError, match=r"health\(\) must be synchronous"):
        @node
        class InvalidAsyncHealth:
            def process(self, sample: StatefulSample) -> StatefulResult:
                return StatefulResult(sample.value)

            async def health(self) -> dict[str, bool]:
                return {"ok": True}


def test_stateful_async_generator_source_is_inferred() -> None:
    @node
    class AsyncCounterSource:
        def __init__(self, count: int = 2):
            self.count = count

        async def process(self) -> StatefulSample:
            for value in range(self.count):
                await asyncio.sleep(0)
                yield StatefulSample(value)

    assert issubclass(AsyncCounterSource, SourceNode)

    async def collect() -> list[StatefulSample]:
        return [item["output"].payload async for item in AsyncCounterSource().produce()]

    assert asyncio.run(collect()) == [StatefulSample(0), StatefulSample(1)]
