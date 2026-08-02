from __future__ import annotations

from abc import ABC
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .cv_types import ManagedBuffer
from .messages import Message
from .lifecycle import LifecycleState, LifecycleTracker


@dataclass(slots=True)
class NodeContext:
    name: str
    run_dir: Path
    project_dir: Path
    runtime_mode: str
    engine: str = "unified"
    device: str = "auto"
    bindings: Mapping[str, Any] = field(default_factory=dict)
    external_links: tuple[Mapping[str, Any], ...] = ()
    _output_allocator: Callable[[int, bool], ManagedBuffer] | None = None

    def allocate_buffer(self, size: int, *, readonly: bool = False) -> ManagedBuffer:
        """Allocate an output buffer from the executor-owned pool.

        In an isolated process this is the zero-copy output path: the child
        writes directly into a parent-owned shared-memory block and returns only
        its descriptor. In-process nodes may also use the allocator when one is
        provided by a device backend.
        """

        if self._output_allocator is None:
            raise RuntimeError(
                "This Nodrix execution context has no executor-owned output allocator; "
                "use BufferPool/SharedBufferPool explicitly or configure process isolation"
            )
        return self._output_allocator(int(size), bool(readonly))

    @property
    def has_output_allocator(self) -> bool:
        return self._output_allocator is not None

    def binding(self, name: str = "session", *, required: bool = True) -> Any:
        """Return a provider resource bound to this Node in the pipeline."""

        value = self.bindings.get(name)
        if value is None and required:
            raise RuntimeError(f"Node {self.name!r} has no binding {name!r}")
        return value


class Node(ABC):
    """Base class for Nodrix nodes.

    ``input_memory`` and ``output_memory`` are optional per-port contracts. A
    missing entry means that the port preserves/accepts any memory domain. The
    graph planner exposes every required copy or device transfer before run.
    """

    input_types: dict[str, str] = {"input": "core.any"}
    output_types: dict[str, str] = {"output": "core.any"}
    input_memory: dict[str, Any] = {}
    output_memory: dict[str, Any] = {}
    # Ports that may be absent from one process() call. This is primarily used
    # by latest_available synchronization for slower multi-rate side inputs.
    optional_inputs: frozenset[str] = frozenset()

    def __init__(self, parameters: dict[str, Any] | None = None) -> None:
        self.parameters = parameters or {}
        self.context: NodeContext | None = None
        self._lifecycle = LifecycleTracker()

    def open(self, context: NodeContext) -> Any:
        self.context = context
        return None

    # Nodrix 1.x lifecycle. Existing 0.x nodes that only override open/flush/close
    # remain source-compatible through these default adapters.
    def configure(self, context: NodeContext) -> Any:
        self._lifecycle.transition(LifecycleState.CONFIGURING)
        return self.open(context)

    def start(self) -> Any:
        self._lifecycle.transition(LifecycleState.RUNNING)
        return None

    def drain(self) -> dict[str, Message] | None | Any:
        self._lifecycle.transition(LifecycleState.DRAINING)
        return self.flush()

    def stop(self) -> Any:
        self._lifecycle.transition(LifecycleState.STOPPING)
        try:
            return self.close()
        finally:
            self._lifecycle.transition(LifecycleState.STOPPED)

    @property
    def lifecycle_state(self) -> str:
        return self._lifecycle.snapshot().state

    def health(self) -> dict[str, Any]:
        return self._lifecycle.snapshot().as_dict()

    def runtime_info(self) -> dict[str, Any]:
        """Return lightweight backend/device information for diagnostics."""
        return {}

    def allocate_output(self, size: int, *, readonly: bool = False) -> ManagedBuffer:
        if self.context is None:
            raise RuntimeError("Node is not open")
        return self.context.allocate_buffer(size, readonly=readonly)

    def process(self, inputs: dict[str, Message]) -> dict[str, Message] | None | Any:
        raise NotImplementedError

    def flush(self) -> dict[str, Message] | None | Any:
        return None

    def close(self) -> Any:
        return None


class SourceNode(Node):
    """Node that produces messages and has no input ports."""

    input_types: dict[str, str] = {}
    input_memory: dict[str, Any] = {}

    def produce(self) -> Iterator[dict[str, Message]] | AsyncIterator[dict[str, Message]]:
        raise NotImplementedError


class SinkNode(Node):
    """Semantic marker for nodes that normally have no output ports."""

    output_types: dict[str, str] = {}
    output_memory: dict[str, Any] = {}
