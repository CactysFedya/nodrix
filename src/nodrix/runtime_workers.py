from __future__ import annotations

import inspect
import json
import time

from .cv_types import TYPE_REGISTRY, normalize_payload
from .errors import RuntimeGraphError
from .messages import Message
from .process_host import ProcessNodeProxy
from .lifecycle import HealthStatus, LifecycleState

try:
    from ._native_queue import BoundedQueue as _NativeBoundedQueue
except Exception:  # pragma: no cover
    _NativeBoundedQueue = None


from .runtime_components import LoadedNode
from .runtime_primitives import (
    Received,
    RuntimeAsyncBridge,
    RuntimeEdgeQueue,
    _EOS,
    _estimate_message_bytes,
)


class RuntimeWorkerMixin:
    """Execution workers over already-materialized runtime mechanics.

    The worker hot path deliberately does not read PipelineManifest.
    Its host supplies the small runtime-level values required for message
    processing, while queue routing uses backend-neutral RuntimeEdgeQueue
    bindings.
    """

    _runtime_type_validation: str
    _message_scope_id: str
    def _run_source(self, loaded: LoadedNode, bridge: RuntimeAsyncBridge) -> None:
        produced = loaded.node.produce()
        if hasattr(produced, "__aiter__"):
            async_iter = produced.__aiter__()
            while not self._stop.is_set():
                try:
                    outputs = bridge.resolve(async_iter.__anext__())
                except StopAsyncIteration:
                    break
                loaded.node._lifecycle.message_started()
                start = time.perf_counter_ns()
                self._publish(loaded, outputs)
                loaded.stats.observe(time.perf_counter_ns() - start)  # type: ignore[union-attr]
                loaded.node._lifecycle.message_completed()
        else:
            for outputs in produced:  # type: ignore[union-attr]
                if self._stop.is_set():
                    break
                loaded.node._lifecycle.message_started()
                start = time.perf_counter_ns()
                self._publish(loaded, outputs)
                loaded.stats.observe(time.perf_counter_ns() - start)  # type: ignore[union-attr]
                loaded.node._lifecycle.message_completed()
        self._publish_eos(loaded)

    def _run_processor(
        self,
        loaded: LoadedNode,
        bridge: RuntimeAsyncBridge,
        *,
        async_process: bool,
        async_flush: bool,
    ) -> None:
        input_ports = tuple(loaded.inputs)
        process = loaded.node.process
        while not self._stop.is_set():
            received = self._receive_synchronized(loaded, input_ports)
            if received is None:
                break
            process_inputs = {port: item.message for port, item in received.items()}
            loaded.watchdog_triggered = False
            loaded.node._lifecycle.message_started()
            start = time.perf_counter_ns()
            try:
                result = bridge.resolve(process(process_inputs)) if async_process else process(process_inputs)
            except BaseException as exc:
                if (
                    loaded.binding.failure_policy == "fallback_node"
                    and not loaded.fallback_active
                ):
                    self._activate_fallback(loaded, bridge, exc)
                    process = loaded.node.process
                    async_process = inspect.iscoroutinefunction(process)
                    result = (
                        bridge.resolve(process(process_inputs))
                        if async_process
                        else process(process_inputs)
                    )
                    loaded.stats.errors += 1  # type: ignore[union-attr]
                elif loaded.binding.failure_policy == "skip_message":
                    loaded.stats.errors += 1  # type: ignore[union-attr]
                    loaded.node._lifecycle.error(exc)
                    loaded.node._lifecycle.transition(LifecycleState.RUNNING, status=HealthStatus.DEGRADED)
                    continue
                elif loaded.binding.failure_policy in {"disable_branch", "isolate_branch"}:
                    loaded.stats.errors += 1  # type: ignore[union-attr]
                    loaded.node._lifecycle.error(exc)
                    loaded.node._lifecycle.transition(LifecycleState.FAILED, status=HealthStatus.UNHEALTHY)
                    self._publish_eos(loaded)
                    return
                else:
                    raise
            loaded.stats.observe(time.perf_counter_ns() - start, received)  # type: ignore[union-attr]
            loaded.node._lifecycle.message_completed()
            if result:
                self._publish(loaded, result)
        flushed = bridge.resolve(loaded.node.drain()) if async_flush else loaded.node.drain()
        if flushed:
            self._publish(loaded, flushed)
        self._publish_eos(loaded)

    def _activate_fallback(
        self,
        loaded: LoadedNode,
        bridge: RuntimeAsyncBridge,
        primary_error: BaseException,
    ) -> None:
        fallback_uses = loaded.binding.fallback_uses
        if not fallback_uses:
            raise RuntimeGraphError(
                f"Node {loaded.name!r} has no configured fallback"
            )
        old_node = loaded.node
        context = old_node.context
        if context is None:
            raise RuntimeGraphError(
                f"Node {loaded.name!r} failed before a fallback could be configured"
            )
        bridge.resolve(old_node.stop())
        fallback = self._load_node(
            fallback_uses,
            dict(
                loaded.binding.parameters
            ),
        )
        if (
            dict(fallback.input_types) != dict(old_node.input_types)
            or dict(fallback.output_types) != dict(old_node.output_types)
        ):
            raise RuntimeGraphError(
                f"Node {loaded.name!r} fallback contracts changed after validation"
            )
        bridge.resolve(fallback.configure(context))
        fallback._lifecycle.transition(LifecycleState.READY)
        fallback._lifecycle.transition(LifecycleState.STARTING)
        bridge.resolve(fallback.start())
        fallback._lifecycle.transition(
            LifecycleState.DEGRADED,
            status=HealthStatus.DEGRADED,
            reason=f"fallback after {type(primary_error).__name__}: {primary_error}",
        )
        loaded.node = fallback
        loaded.fallback_active = True
        self._emit_event(
            "node_fallback",
            node=loaded.name,
            uses=fallback_uses,
            primary_error=f"{type(primary_error).__name__}: {primary_error}",
        )

    def _blocking_received(self, edge: RuntimeEdgeQueue) -> Received | None:
        item = edge.get()
        if item is None or item is _EOS:
            return None
        return item

    def _receive_synchronized(self, loaded: LoadedNode, input_ports: tuple[str, ...]) -> dict[str, Received] | None:
        if len(input_ports) == 1:
            item = self._blocking_received(loaded.inputs[input_ports[0]])
            return None if item is None else {input_ports[0]: item}

        policy = loaded.binding.synchronization_policy
        if policy == "zip":
            result: dict[str, Received] = {}
            for port in input_ports:
                item = self._blocking_received(loaded.inputs[port])
                if item is None:
                    return None
                result[port] = item
            return result
        if policy == "latest_available":
            return self._receive_latest(loaded, input_ports)
        return self._receive_matching(loaded, input_ports, approximate=(policy == "approximate_timestamp"))

    def _receive_latest(self, loaded: LoadedNode, input_ports: tuple[str, ...]) -> dict[str, Received] | None:
        trigger = loaded.binding.synchronization_trigger_port or input_ports[0]
        item = self._blocking_received(loaded.inputs[trigger])
        if item is None:
            return None
        loaded.latest_inputs[trigger] = item
        for port in input_ports:
            if port == trigger:
                continue
            optional = port in getattr(loaded.node, "optional_inputs", ())
            if port not in loaded.latest_inputs and not optional:
                initial = self._blocking_received(loaded.inputs[port])
                if initial is None:
                    return None
                loaded.latest_inputs[port] = initial
            while True:
                newest = loaded.inputs[port].try_get()
                if newest is None or newest is _EOS:
                    break
                if port in loaded.latest_inputs:
                    loaded.stats.synchronization_drops += 1  # type: ignore[union-attr]
                loaded.latest_inputs[port] = newest
        return {port: loaded.latest_inputs[port] for port in input_ports if port in loaded.latest_inputs}

    def _receive_matching(
        self, loaded: LoadedNode, input_ports: tuple[str, ...], *, approximate: bool
    ) -> dict[str, Received] | None:
        current: dict[str, Received] = {}
        tolerance_ns = (
            loaded.binding.synchronization_tolerance_ns
        )
        while not self._stop.is_set():
            for port in input_ports:
                if port not in current:
                    item = self._blocking_received(loaded.inputs[port])
                    if item is None:
                        return None
                    current[port] = item
            if approximate:
                timestamps = {port: item.message.timestamp_ns for port, item in current.items()}
                oldest_port = min(timestamps, key=timestamps.get)
                if max(timestamps.values()) - min(timestamps.values()) <= tolerance_ns:
                    return current
                current.pop(oldest_port)
                loaded.stats.synchronization_drops += 1  # type: ignore[union-attr]
            else:
                sequences = {port: item.message.sequence for port, item in current.items()}
                if len(set(sequences.values())) == 1:
                    return current
                oldest_port = min(sequences, key=sequences.get)
                current.pop(oldest_port)
                loaded.stats.synchronization_drops += 1  # type: ignore[union-attr]
        return None

    def _validate_payload(self, loaded: LoadedNode, port: str, message: Message) -> None:
        mode = self._runtime_type_validation
        if mode == "off":
            return
        key = (loaded.name, port)
        if mode == "first" and key in self._validated_ports:
            return
        TYPE_REGISTRY.validate(message.type, message.payload)
        self._validated_ports.add(key)
        loaded.stats.type_validations += 1  # type: ignore[union-attr]

    def _publish(self, loaded: LoadedNode, outputs: dict[str, Message]) -> None:
        for port, message in outputs.items():
            if port not in loaded.node.output_types:
                raise RuntimeGraphError(f"Node {loaded.name!r} emitted unknown port {port!r}")
            expected = loaded.node.output_types[port]
            if expected != "core.any" and message.type != expected:
                raise RuntimeGraphError(
                    f"Node {loaded.name!r} emitted {message.type!r} on {port!r}; expected {expected!r}"
                )
            normalized = normalize_payload(message.type, message.payload)
            if normalized is not message.payload:
                message = message.with_updates(payload=normalized)
            payload_size = _estimate_message_bytes(message)
            if payload_size > loaded.binding.max_message_bytes:
                raise RuntimeGraphError(
                    f"Node {loaded.name!r} emitted {payload_size} bytes, exceeding resources.max_message_bytes="
                    f"{loaded.binding.max_message_bytes}"
                )
            if len(json.dumps(message.metadata, default=str).encode("utf-8")) > 1024 * 1024:
                raise RuntimeGraphError(f"Node {loaded.name!r} emitted metadata larger than 1 MiB")
            self._validate_payload(loaded, port, message)
            source_name = f"{loaded.name}.{port}"
            outgoing = message.with_updates(
                stream_id=source_name,
                source_id=message.source_id or source_name,
                pipeline_id=message.pipeline_id or self._message_scope_id,
                run_id=message.run_id or self._run_id,
            )
            if (
                self._recording_writer is not None
                and (
                    not self._recording_streams
                    or source_name in self._recording_streams
                )
            ):
                self._recording_writer.write(outgoing)
            for edge in loaded.outputs.get(port, ()):
                target_endpoint = edge.binding.target
                target_node, target_port = target_endpoint.split(".", 1)
                target_type = self.nodes[target_node].node.input_types[target_port]
                if target_type != "core.any" and outgoing.type != target_type:
                    raise RuntimeGraphError(
                        f"Message {outgoing.type!r} from {source_name!r} cannot enter "
                        f"{target_endpoint!r}; expected {target_type!r}"
                    )
                edge.put(outgoing.fork())
            if self._stream_publisher is not None:
                self._stream_publisher.publish(source_name, outgoing)

    def _publish_eos(self, loaded: LoadedNode) -> None:
        for queues in loaded.outputs.values():
            for edge in queues:
                edge.put_control(_EOS)

    def _watchdog_loop(self) -> None:
        while not self._stop.wait(0.1):
            now = time.monotonic_ns()
            for loaded in self.nodes.values():
                binding = loaded.binding
                if binding.health_timeout_ns <= 0:
                    continue
                health = loaded.node._lifecycle.snapshot()
                last = health.last_message_ns or health.last_completion_ns
                if not health.ready or last is None:
                    continue
                if now - last <= binding.health_timeout_ns or loaded.watchdog_triggered:
                    continue
                loaded.watchdog_triggered = True
                loaded.node._lifecycle.error(f"health timeout after {binding.health_timeout_ns // 1_000_000} ms")
                if binding.health_on_timeout == "stop_pipeline":
                    self._record_error(loaded.name, TimeoutError(f"node health timeout: {loaded.name}"))
                    return
                if binding.health_on_timeout == "restart" and isinstance(loaded.node, ProcessNodeProxy):
                    loaded.node._lifecycle.mark_restart()
                    loaded.node.interrupt()
                    # The blocked worker observes EOF and performs the serialized restart.
                    loaded.node._lifecycle.transition(LifecycleState.RESTARTING, status=HealthStatus.DEGRADED)

    def _record_error(self, name: str, exc: BaseException) -> None:
        with self._error_lock:
            if not self._errors:
                self._errors.append((name, exc))
                self._stop.set()
                self._start.set()
                for edge in self.edges:
                    edge.close()
