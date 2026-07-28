from __future__ import annotations

from dataclasses import asdict
import gc
import multiprocessing as mp
from multiprocessing.connection import Connection
from pathlib import Path
import time
import threading
from typing import Any, Iterator

from .cv_types import EncodedFrame, Frame, ManagedBuffer, Tensor
from .messages import Message
from .node import Node, NodeContext, SourceNode
from .registry import load_node_class
from .shared_memory import (
    OneShotSharedBuffer,
    SharedBufferDescriptor,
    SharedBufferPool,
    descriptor_for_buffer,
    open_shared_buffer,
)
from .wire import WirePacket, decode_packet_parts, encode_message


def _payload_managed_buffer(message: Message) -> ManagedBuffer | None:
    payload = message.payload
    if isinstance(payload, ManagedBuffer):
        return payload
    if isinstance(payload, (Frame, EncodedFrame, Tensor)):
        return payload.buffer
    return None


def _packet_payload_bytes(packet: WirePacket) -> bytes:
    if len(packet.payload_parts) == 1:
        return bytes(packet.payload_parts[0])
    data = bytearray(sum(part.nbytes for part in packet.payload_parts))
    view = memoryview(data)
    offset = 0
    for part in packet.payload_parts:
        view[offset : offset + part.nbytes] = part
        offset += part.nbytes
    return bytes(data)


def _descriptor_key(descriptor: SharedBufferDescriptor) -> tuple[str, int]:
    return descriptor.name, descriptor.offset


class _ChildOutputAllocator:
    """Maps executor-owned output slots into an isolated worker."""

    def __init__(self, descriptors: list[SharedBufferDescriptor]) -> None:
        self.descriptors = descriptors
        self._buffers: list[ManagedBuffer | None] = [None] * len(descriptors)
        self._next = 0

    def allocate(self, size: int, readonly: bool = False) -> ManagedBuffer:
        size = int(size)
        if size <= 0:
            raise ValueError("output allocation size must be positive")
        for index in range(self._next, len(self.descriptors)):
            descriptor = self.descriptors[index]
            if size <= descriptor.size:
                mapped = open_shared_buffer(descriptor)
                mapped.length = size
                mapped.readonly = bool(readonly)
                self._buffers[index] = mapped
                self._next = index + 1
                return mapped
        raise BufferError(
            f"isolated output requires {size} bytes but no executor-owned shared slot is available"
        )

    def allowed_ranges(self) -> list[SharedBufferDescriptor]:
        return self.descriptors

    def close(self) -> None:
        for buffer in self._buffers:
            if buffer is not None:
                buffer.release()
        self._buffers.clear()


def _descriptor_in_slots(
    descriptor: SharedBufferDescriptor,
    slots: list[SharedBufferDescriptor] | None,
) -> int | None:
    for index, slot in enumerate(slots or ()):
        if descriptor.name != slot.name:
            continue
        if descriptor.offset < slot.offset:
            continue
        if descriptor.offset + descriptor.size <= slot.offset + slot.size:
            return index
    return None


def _encode_ipc_message(
    message: Message,
    *,
    pool: SharedBufferPool | None,
    threshold: int,
    child_output: bool = False,
    output_slots: list[SharedBufferDescriptor] | None = None,
    output_allocator: _ChildOutputAllocator | None = None,
) -> tuple[dict[str, Any], list[Any], int]:
    packet = encode_message(message)
    payload_size = sum(part.nbytes for part in packet.payload_parts)
    packet_info: dict[str, Any] = {
        "header": packet.header,
        "type": packet.type_name,
        "metadata": packet.metadata,
    }
    leases: list[Any] = []
    copies = 0

    managed = _payload_managed_buffer(message)
    descriptor = descriptor_for_buffer(managed) if managed is not None and len(packet.payload_parts) == 1 else None
    slot_index = _descriptor_in_slots(descriptor, output_slots) if descriptor is not None else None
    if descriptor is not None and descriptor.size == payload_size and (not child_output or slot_index is not None):
        packet_info["payload"] = {
            "shared": asdict(descriptor),
            "unlink": False,
            "slot": slot_index,
        }
        return packet_info, leases, copies

    if payload_size >= threshold:
        # In a child process first use a parent-owned output slot. This leaves
        # one explicit copy for legacy nodes; allocator-aware nodes above have 0.
        target: ManagedBuffer | None = None
        if child_output and output_allocator is not None:
            try:
                target = output_allocator.allocate(payload_size, readonly=False)
            except BufferError:
                target = None
        if target is not None:
            target.memoryview()[:] = _packet_payload_bytes(packet)
            target.readonly = True
            descriptor = descriptor_for_buffer(target)
            assert descriptor is not None
            slot_index = _descriptor_in_slots(descriptor, output_slots)
            packet_info["payload"] = {
                "shared": asdict(descriptor),
                "unlink": False,
                "slot": slot_index,
            }
            copies += 1
        elif child_output or pool is None or payload_size > pool.block_size:
            allocation = OneShotSharedBuffer(payload_size, readonly=False)
            target = allocation.buffer()
            target.memoryview()[:] = _packet_payload_bytes(packet)
            target.readonly = True
            descriptor = SharedBufferDescriptor(
                allocation.descriptor.name, payload_size, 0, True, allocation.descriptor.generation
            )
            packet_info["payload"] = {"shared": asdict(descriptor), "unlink": child_output, "slot": None}
            leases.append(allocation)
            copies += 1
        else:
            target = pool.acquire(payload_size, readonly=False)
            target.memoryview()[:] = _packet_payload_bytes(packet)
            target.readonly = True
            descriptor = descriptor_for_buffer(target)
            assert descriptor is not None
            packet_info["payload"] = {"shared": asdict(descriptor), "unlink": False, "slot": None}
            leases.append(target.lease)
            copies += 1
    else:
        packet_info["payload"] = {"bytes": _packet_payload_bytes(packet)}
        copies += 1 if payload_size else 0
    return packet_info, leases, copies


def _attach_lease(message: Message, lease: Any) -> None:
    message.lease = lease
    managed = _payload_managed_buffer(message)
    if managed is not None:
        managed.lease = lease
        managed.memory_type = managed.memory_type.SHARED
        managed.device = "shm"


def _decode_ipc_message(
    value: dict[str, Any],
    *,
    output_slot_buffers: list[ManagedBuffer] | None = None,
) -> tuple[Message, list[Any], bool, int | None]:
    payload_spec = value["payload"]
    leases: list[Any] = []
    needs_ack = False
    used_slot: int | None = None
    if "shared" in payload_spec:
        descriptor = SharedBufferDescriptor(**payload_spec["shared"])
        slot_index = payload_spec.get("slot")
        if slot_index is not None and output_slot_buffers is not None:
            slot_index = int(slot_index)
            slot = output_slot_buffers[slot_index]
            slot_descriptor = descriptor_for_buffer(slot)
            if slot_descriptor is None:
                raise RuntimeError("Nodrix output slot lost its shared-memory descriptor")
            relative = descriptor.offset - slot_descriptor.offset
            payload = slot.memoryview()[relative : relative + descriptor.size]
            used_slot = slot_index
        else:
            managed = open_shared_buffer(descriptor, unlink=bool(payload_spec.get("unlink")))
            leases.append(managed.lease)
            payload = managed.memoryview()
            needs_ack = bool(payload_spec.get("unlink"))
    else:
        payload = memoryview(payload_spec.get("bytes", b""))
    message = decode_packet_parts(value["header"], value["type"], value["metadata"], payload)
    if used_slot is not None and output_slot_buffers is not None:
        # Keep the complete parent-owned slot alive until the final downstream
        # consumer releases the decoded message.
        _attach_lease(message, output_slot_buffers[used_slot])
    elif leases:
        _attach_lease(message, leases if len(leases) > 1 else leases[0])
    return message, leases, needs_ack, used_slot


def _load_child_node(uses: str, base_dir: Path, parameters: dict[str, Any]) -> Node:
    if uses.startswith("native:"):
        from .native_plugin import NativePluginNode

        body = uses.removeprefix("native:")
        library, node_type = body.rsplit("#", 1)
        path = Path(library).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        return NativePluginNode(path, node_type, parameters)
    cls = load_node_class(uses, base_dir=base_dir)
    return cls(parameters)


def _child_main(connection: Connection, config: dict[str, Any]) -> None:
    node: Node | None = None
    producer: Any = None
    context: NodeContext | None = None
    try:
        base_dir = Path(config["base_dir"])
        node = _load_child_node(config["uses"], base_dir, config["parameters"])
        context = NodeContext(
            name=config["name"],
            run_dir=Path(config["run_dir"]),
            project_dir=base_dir,
            runtime_mode=config["runtime_mode"],
            engine="unified-process",
            device=config.get("device", "auto"),
        )
        node.configure(context)
        affinity = config.get("cpu_affinity") or []
        if affinity:
            try:
                import os
                os.sched_setaffinity(0, set(int(item) for item in affinity))
            except (AttributeError, OSError):
                pass
        memory_limit_mb = config.get("memory_limit_mb")
        cpu_limit = config.get("cpu_limit")
        try:
            import resource
            if memory_limit_mb:
                limit = int(memory_limit_mb) * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            if cpu_limit:
                seconds = max(1, int(float(cpu_limit)))
                resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
        except (ImportError, OSError, ValueError):
            pass
        node.start()
        connection.send({"ok": True, "event": "ready", "source": isinstance(node, SourceNode)})
        threshold = int(config["threshold"])
        while True:
            command = connection.recv()
            operation = command["op"]
            if operation == "close":
                node.stop()
                connection.send({"ok": True})
                return
            input_leases: list[Any] = []
            output_allocator: _ChildOutputAllocator | None = None
            try:
                descriptors = [SharedBufferDescriptor(**item) for item in command.get("output_slots", [])]
                output_allocator = _ChildOutputAllocator(descriptors)
                context._output_allocator = output_allocator.allocate if descriptors else None
                eos = False
                if operation == "process":
                    inputs: dict[str, Message] = {}
                    for port, encoded in command["inputs"].items():
                        message, leases, _, _ = _decode_ipc_message(encoded)
                        inputs[port] = message
                        input_leases.extend(leases)
                    result = node.process(inputs)
                elif operation == "flush":
                    result = node.drain()
                elif operation == "produce_next":
                    if not isinstance(node, SourceNode):
                        raise TypeError("produce_next is only valid for SourceNode")
                    if producer is None:
                        producer = iter(node.produce())
                    try:
                        result = next(producer)
                    except StopIteration:
                        result = None
                        eos = True
                else:
                    raise ValueError(f"Unknown process-host operation: {operation}")
                encoded_outputs: dict[str, Any] = {}
                output_allocations: list[Any] = []
                copies = 0
                for port, message in (result or {}).items():
                    encoded, allocations, item_copies = _encode_ipc_message(
                        message,
                        pool=None,
                        threshold=threshold,
                        child_output=True,
                        output_slots=descriptors,
                        output_allocator=output_allocator,
                    )
                    encoded_outputs[port] = encoded
                    output_allocations.extend(allocations)
                    copies += item_copies
                connection.send({"ok": True, "outputs": encoded_outputs, "copies": copies, "eos": eos})
                if output_allocations:
                    acknowledgement = connection.recv()
                    if acknowledgement.get("op") != "release_outputs":
                        raise RuntimeError("Invalid Nodrix process output acknowledgement")
                    for allocation in output_allocations:
                        allocation.lease.release()
            except BaseException as exc:
                connection.send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            finally:
                context._output_allocator = None
                try:
                    del inputs
                except UnboundLocalError:
                    pass
                gc.collect()
                for lease in input_leases:
                    lease.release()
                if output_allocator is not None:
                    output_allocator.close()
    except BaseException as exc:
        try:
            connection.send({"ok": False, "fatal": True, "error": f"{type(exc).__name__}: {exc}"})
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


class ProcessNodeError(RuntimeError):
    pass


class ProcessNodeProxy(Node):
    """Runs a regular Nodrix node in an isolated worker process."""

    def __init__(
        self,
        *,
        name: str,
        uses: str,
        base_dir: Path,
        parameters: dict[str, Any],
        input_types: dict[str, str],
        output_types: dict[str, str],
        input_memory: dict[str, Any] | None = None,
        output_memory: dict[str, Any] | None = None,
        block_size: int = 8 * 1024 * 1024,
        capacity: int = 8,
        output_block_size: int | None = None,
        output_capacity: int | None = None,
        threshold: int,
        failure_policy: str,
        max_restarts: int,
        backoff_ms: int,
        cpu_affinity: list[int],
        device: str = "auto",
        memory_limit_mb: int | None = None,
        cpu_limit: float | None = None,
    ) -> None:
        super().__init__(parameters)
        self.name = name
        self.uses = uses
        self.base_dir = base_dir
        self.input_types = dict(input_types)
        self.output_types = dict(output_types)
        self.input_memory = dict(input_memory or {})
        self.output_memory = dict(output_memory or {})
        self.threshold = int(threshold)
        self.failure_policy = failure_policy
        self.max_restarts = int(max_restarts)
        self.backoff_ms = int(backoff_ms)
        self.cpu_affinity = list(cpu_affinity)
        self.device = device
        self.memory_limit_mb = memory_limit_mb
        self.cpu_limit = cpu_limit
        self.input_pool = SharedBufferPool(block_size, capacity, name=f"nodrix-in-{name}-{int(time.time_ns())}")
        output_block_size = block_size if output_block_size is None else int(output_block_size)
        output_capacity = capacity if output_capacity is None else int(output_capacity)
        self.output_pool = SharedBufferPool(
            output_block_size, output_capacity, name=f"nodrix-out-{name}-{int(time.time_ns())}"
        )
        # compatibility alias
        self.pool = self.input_pool
        self._ctx = mp.get_context("spawn")
        self._process: mp.Process | None = None
        self._connection: Connection | None = None
        self._restart_lock = threading.RLock()
        self._generation = 0
        self.restarts = 0
        self.input_copies = 0
        self.output_copies = 0
        self.output_zero_copy = 0
        self._last_eos = False

    def open(self, context: NodeContext) -> None:
        super().open(context)
        self._start_child()

    def _start_child(self) -> None:
        if self.context is None:
            raise RuntimeError("ProcessNodeProxy has no NodeContext")
        parent, child = self._ctx.Pipe(duplex=True)
        config = {
            "name": self.name,
            "uses": self.uses,
            "base_dir": str(self.base_dir),
            "parameters": self.parameters,
            "run_dir": str(self.context.run_dir),
            "runtime_mode": self.context.runtime_mode,
            "threshold": self.threshold,
            "cpu_affinity": self.cpu_affinity,
            "device": self.device,
            "memory_limit_mb": self.memory_limit_mb,
            "cpu_limit": self.cpu_limit,
        }
        process = self._ctx.Process(target=_child_main, args=(child, config), name=f"nodrix-process:{self.name}")
        process.start()
        child.close()
        self._process = process
        self._connection = parent
        self._generation += 1
        if not parent.poll(15.0):
            self._terminate()
            raise ProcessNodeError(f"Isolated node {self.name!r} did not become ready")
        response = parent.recv()
        if not response.get("ok"):
            self._terminate()
            raise ProcessNodeError(response.get("error", "isolated node startup failed"))

    def _terminate(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=2.0)
            self._process = None

    def interrupt(self) -> None:
        """Terminate a hung child; the worker call owns the serialized restart."""
        with self._restart_lock:
            self._terminate()

    def restart(self) -> bool:
        """Terminate and restart the isolated worker for explicit control-plane recovery."""
        return self._restart(force=True)

    def _restart(self, force: bool = False) -> bool:
        with self._restart_lock:
            if (not force and self.failure_policy != "restart") or self.restarts >= self.max_restarts:
                return False
            self._terminate()
            self.restarts += 1
            if self.backoff_ms:
                time.sleep(self.backoff_ms / 1000.0)
            self._start_child()
            return True

    def _reserve_output_slots(self) -> list[ManagedBuffer]:
        count = max(1, len(self.output_types)) if self.output_types else 0
        slots: list[ManagedBuffer] = []
        try:
            for _ in range(count):
                slots.append(self.output_pool.acquire(self.output_pool.block_size, readonly=False))
            return slots
        except BaseException:
            for slot in slots:
                slot.release()
            raise

    def _call(self, operation: str, inputs: dict[str, Message] | None = None) -> dict[str, Message] | None:
        attempts = 0
        while True:
            attempts += 1
            call_generation = self._generation
            leases: list[Any] = []
            output_slots: list[ManagedBuffer] = []
            used_slots: set[int] = set()
            try:
                if self._connection is None or self._process is None or not self._process.is_alive():
                    raise EOFError("isolated node process is not running")
                encoded_inputs: dict[str, Any] = {}
                for port, message in (inputs or {}).items():
                    encoded, item_leases, copies = _encode_ipc_message(
                        message, pool=self.input_pool, threshold=self.threshold
                    )
                    encoded_inputs[port] = encoded
                    leases.extend(item_leases)
                    self.input_copies += copies
                output_slots = self._reserve_output_slots()
                output_descriptors = []
                for slot in output_slots:
                    descriptor = descriptor_for_buffer(slot)
                    assert descriptor is not None
                    output_descriptors.append(asdict(descriptor))
                self._connection.send({"op": operation, "inputs": encoded_inputs, "output_slots": output_descriptors})
                response = self._connection.recv()
                if not response.get("ok"):
                    raise ProcessNodeError(response.get("error", "isolated node failed"))
                self._last_eos = bool(response.get("eos", False))
                outputs: dict[str, Message] = {}
                needs_ack = False
                for port, encoded in response.get("outputs", {}).items():
                    message, output_leases, item_ack, used_slot = _decode_ipc_message(
                        encoded, output_slot_buffers=output_slots
                    )
                    outputs[port] = message
                    needs_ack = needs_ack or item_ack
                    if used_slot is not None:
                        used_slots.add(used_slot)
                        self.output_zero_copy += 1 if int(response.get("copies", 0)) == 0 else 0
                    del output_leases
                self.output_copies += int(response.get("copies", 0))
                if needs_ack:
                    self._connection.send({"op": "release_outputs"})
                return outputs or None
            except (EOFError, BrokenPipeError, OSError, ProcessNodeError) as exc:
                if self.failure_policy == "skip_message":
                    return None
                if self._generation != call_generation and self._process is not None and self._process.is_alive():
                    continue
                if attempts <= self.max_restarts + 1 and self._restart():
                    continue
                raise ProcessNodeError(f"Isolated node {self.name!r} failed: {exc}") from exc
            finally:
                gc.collect()
                for lease in leases:
                    if lease is not None:
                        lease.release()
                for index, slot in enumerate(output_slots):
                    if index not in used_slots:
                        slot.release()

    def process(self, inputs: dict[str, Message]) -> dict[str, Message] | None:
        return self._call("process", inputs)

    def flush(self) -> dict[str, Message] | None:
        return self._call("flush")

    def close(self) -> None:
        if self._connection is not None and self._process is not None and self._process.is_alive():
            try:
                self._connection.send({"op": "close"})
                if self._connection.poll(3.0):
                    self._connection.recv()
            except (EOFError, BrokenPipeError, OSError):
                pass
        self._terminate()
        self.input_pool.close()
        self.output_pool.close()

    def transport_report(self) -> dict[str, Any]:
        return {
            "isolation": "process",
            "restarts": self.restarts,
            "input_payload_copies": self.input_copies,
            "output_payload_copies": self.output_copies,
            "zero_copy_outputs": self.output_zero_copy,
            "shared_input_pool": self.input_pool.stats(),
            "shared_output_pool": self.output_pool.stats(),
        }


class ProcessSourceProxy(ProcessNodeProxy, SourceNode):
    """Process-isolated synchronous SourceNode introduced in Nodrix 0.9."""

    input_types: dict[str, str] = {}

    def produce(self) -> Iterator[dict[str, Message]]:
        while True:
            outputs = self._call("produce_next")
            if self._last_eos:
                return
            if outputs:
                yield outputs
