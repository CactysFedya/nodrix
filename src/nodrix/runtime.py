from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import time
from typing import Any

from .errors import RuntimeGraphError
from .manifest import EdgeConfig, PipelineManifest, dump_manifest
from .messages import Message
from .node import Node, NodeContext, SourceNode
from .registry import load_node_class


_EOS = object()


@dataclass(slots=True)
class NodeStats:
    messages: int = 0
    errors: int = 0
    total_process_ns: int = 0
    min_process_ns: int | None = None
    max_process_ns: int = 0

    def observe(self, duration_ns: int) -> None:
        self.messages += 1
        self.total_process_ns += duration_ns
        self.min_process_ns = duration_ns if self.min_process_ns is None else min(self.min_process_ns, duration_ns)
        self.max_process_ns = max(self.max_process_ns, duration_ns)

    def report(self) -> dict[str, Any]:
        mean = self.total_process_ns / self.messages if self.messages else 0
        return {
            "messages": self.messages,
            "errors": self.errors,
            "mean_ms": mean / 1e6,
            "min_ms": (self.min_process_ns or 0) / 1e6,
            "max_ms": self.max_process_ns / 1e6,
            "total_ms": self.total_process_ns / 1e6,
        }


@dataclass(slots=True)
class EdgeStats:
    source: str
    target: str
    enqueued: int = 0
    dropped: int = 0
    max_depth: int = 0


class EdgeQueue:
    def __init__(self, edge: EdgeConfig) -> None:
        self.edge = edge
        self.queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=edge.queue.capacity)
        self.stats = EdgeStats(edge.source, edge.target)

    async def put(self, item: Any) -> None:
        policy = self.edge.queue.policy
        if item is _EOS:
            # EOS is ordered after already accepted data and is never dropped.
            await self.queue.put(item)
            return

        if policy == "block":
            await self.queue.put(item)
        elif policy == "latest":
            while self.queue.full():
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                    self.stats.dropped += 1
                except asyncio.QueueEmpty:
                    break
            await self.queue.put(item)
        elif policy == "drop_oldest":
            if self.queue.full():
                self.queue.get_nowait()
                self.queue.task_done()
                self.stats.dropped += 1
            await self.queue.put(item)
        elif policy == "drop_newest":
            if self.queue.full():
                self.stats.dropped += 1
                return
            await self.queue.put(item)
        else:  # pragma: no cover
            raise RuntimeGraphError(f"Unsupported queue policy: {policy}")

        self.stats.enqueued += 1
        self.stats.max_depth = max(self.stats.max_depth, self.queue.qsize())

    async def get(self) -> Any:
        return await self.queue.get()

    def task_done(self) -> None:
        self.queue.task_done()


@dataclass(slots=True)
class LoadedNode:
    name: str
    node: Node
    inputs: dict[str, EdgeQueue] = field(default_factory=dict)
    outputs: dict[str, list[EdgeQueue]] = field(default_factory=lambda: defaultdict(list))
    stats: NodeStats = field(default_factory=NodeStats)


class PipelineRuntime:
    def __init__(
        self,
        manifest: PipelineManifest,
        manifest_path: Path,
        run_root: Path | None = None,
    ) -> None:
        self.manifest = manifest
        self.manifest_path = manifest_path.resolve()
        self.base_dir = self.manifest_path.parent
        self.run_root = (run_root or self.base_dir / ".nodrix" / "runs").resolve()
        self.nodes: dict[str, LoadedNode] = {}
        self.edges: list[EdgeQueue] = []

    def build(self) -> None:
        for name, config in self.manifest.nodes.items():
            cls = load_node_class(config.uses, base_dir=self.base_dir)
            self.nodes[name] = LoadedNode(name=name, node=cls(config.parameters))

        for edge_config in self.manifest.edges:
            src_name, src_port = edge_config.source.split(".", 1)
            dst_name, dst_port = edge_config.target.split(".", 1)
            if src_name not in self.nodes:
                raise RuntimeGraphError(f"Unknown source node: {src_name}")
            if dst_name not in self.nodes:
                raise RuntimeGraphError(f"Unknown target node: {dst_name}")
            src_node = self.nodes[src_name].node
            dst_node = self.nodes[dst_name].node
            if src_port not in src_node.output_types:
                raise RuntimeGraphError(f"Node {src_name!r} has no output port {src_port!r}")
            if dst_port not in dst_node.input_types:
                raise RuntimeGraphError(f"Node {dst_name!r} has no input port {dst_port!r}")
            source_type = src_node.output_types[src_port]
            target_type = dst_node.input_types[dst_port]
            if not self._types_compatible(source_type, target_type):
                raise RuntimeGraphError(
                    f"Type mismatch {edge_config.source} ({source_type}) -> "
                    f"{edge_config.target} ({target_type})"
                )
            if dst_port in self.nodes[dst_name].inputs:
                raise RuntimeGraphError(
                    f"Input {edge_config.target} already has a connection; "
                    "fan-in requires an explicit merge node"
                )
            edge = EdgeQueue(edge_config)
            self.edges.append(edge)
            self.nodes[src_name].outputs[src_port].append(edge)
            self.nodes[dst_name].inputs[dst_port] = edge

        for name, loaded in self.nodes.items():
            expected = set(loaded.node.input_types)
            connected = set(loaded.inputs)
            if expected != connected:
                missing = sorted(expected - connected)
                raise RuntimeGraphError(f"Node {name!r} has unconnected inputs: {missing}")

        sources = [n for n in self.nodes.values() if isinstance(n.node, SourceNode)]
        if not sources:
            raise RuntimeGraphError("Pipeline requires at least one SourceNode")

    @staticmethod
    def _types_compatible(source: str, target: str) -> bool:
        return source == target or source == "core.any" or target == "core.any"

    def describe(self) -> dict[str, Any]:
        if not self.nodes:
            self.build()
        return {
            "name": self.manifest.metadata.name,
            "mode": self.manifest.runtime.mode,
            "nodes": {
                name: {
                    "class": f"{loaded.node.__class__.__module__}.{loaded.node.__class__.__name__}",
                    "inputs": loaded.node.input_types,
                    "outputs": loaded.node.output_types,
                }
                for name, loaded in self.nodes.items()
            },
            "edges": [
                {
                    "from": edge.edge.source,
                    "to": edge.edge.target,
                    "type": self._edge_type(edge.edge.source),
                    "queue": edge.edge.queue.model_dump(),
                }
                for edge in self.edges
            ],
        }

    def _edge_type(self, source: str) -> str:
        node, port = source.split(".", 1)
        return self.nodes[node].node.output_types[port]

    async def run(self) -> dict[str, Any]:
        if not self.nodes:
            self.build()
        run_dir = self._create_run_dir()
        dump_manifest(self.manifest, run_dir / "manifest.resolved.yaml")
        started_ns = time.perf_counter_ns()

        for loaded in self.nodes.values():
            opened = loaded.node.open(NodeContext(
                name=loaded.name,
                run_dir=run_dir,
                project_dir=self.base_dir,
                runtime_mode=self.manifest.runtime.mode,
                engine="python",
            ))
            if inspect.isawaitable(opened):
                await opened

        tasks: list[asyncio.Task[Any]] = []
        for loaded in self.nodes.values():
            if isinstance(loaded.node, SourceNode):
                tasks.append(asyncio.create_task(self._run_source(loaded), name=loaded.name))
            else:
                tasks.append(asyncio.create_task(self._run_processor(loaded), name=loaded.name))

        error: BaseException | None = None
        try:
            await asyncio.gather(*tasks)
        except BaseException as exc:
            error = exc
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            close_errors = []
            for loaded in reversed(list(self.nodes.values())):
                try:
                    closed = loaded.node.close()
                    if inspect.isawaitable(closed):
                        await closed
                except Exception as exc:  # pragma: no cover
                    close_errors.append(f"{loaded.name}: {exc}")

        finished_ns = time.perf_counter_ns()
        report = self._make_report(run_dir, started_ns, finished_ns, error, close_errors)
        (run_dir / "run.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if error is not None:
            raise error
        return report

    async def _run_source(self, loaded: LoadedNode) -> None:
        assert isinstance(loaded.node, SourceNode)
        try:
            produced = loaded.node.produce()
            if hasattr(produced, "__aiter__"):
                async for outputs in produced:
                    start = time.perf_counter_ns()
                    await self._publish(loaded, outputs)
                    loaded.stats.observe(time.perf_counter_ns() - start)
            else:
                for outputs in produced:
                    start = time.perf_counter_ns()
                    await self._publish(loaded, outputs)
                    loaded.stats.observe(time.perf_counter_ns() - start)
        except Exception:
            loaded.stats.errors += 1
            raise
        finally:
            await self._publish_eos(loaded)

    async def _run_processor(self, loaded: LoadedNode) -> None:
        input_ports = list(loaded.inputs)
        try:
            while True:
                # v0.1 synchronizes multi-input nodes by exact sequence.
                inputs = await self._receive_synchronized(loaded, input_ports)
                if inputs is None:
                    break
                start = time.perf_counter_ns()
                result = loaded.node.process(inputs)
                if inspect.isawaitable(result):
                    result = await result
                loaded.stats.observe(time.perf_counter_ns() - start)
                if result:
                    await self._publish(loaded, result)
            flushed = loaded.node.flush()
            if inspect.isawaitable(flushed):
                flushed = await flushed
            if flushed:
                await self._publish(loaded, flushed)
        except Exception:
            loaded.stats.errors += 1
            raise
        finally:
            await self._publish_eos(loaded)

    async def _receive_synchronized(
        self, loaded: LoadedNode, input_ports: list[str]
    ) -> dict[str, Message] | None:
        if len(input_ports) == 1:
            port = input_ports[0]
            edge = loaded.inputs[port]
            item = await edge.get()
            edge.task_done()
            if item is _EOS:
                return None
            return {port: item}

        current: dict[str, Message] = {}
        while True:
            for port in input_ports:
                if port not in current:
                    edge = loaded.inputs[port]
                    item = await edge.get()
                    edge.task_done()
                    if item is _EOS:
                        return None
                    current[port] = item
            sequences = {msg.sequence for msg in current.values()}
            if len(sequences) == 1:
                return current
            max_sequence = max(sequences)
            current = {
                port: msg for port, msg in current.items() if msg.sequence >= max_sequence
            }

    async def _publish(self, loaded: LoadedNode, outputs: dict[str, Message]) -> None:
        for port, message in outputs.items():
            if port not in loaded.node.output_types:
                raise RuntimeGraphError(f"Node {loaded.name!r} emitted unknown port {port!r}")
            expected = loaded.node.output_types[port]
            if expected != "core.any" and message.type != expected:
                raise RuntimeGraphError(
                    f"Node {loaded.name!r} emitted {message.type!r} on {port!r}; expected {expected!r}"
                )
            stream_id = f"{loaded.name}.{port}"
            outgoing = message.with_updates(stream_id=stream_id)
            for edge in loaded.outputs.get(port, []):
                target_node, target_port = edge.edge.target.split(".", 1)
                target_type = self.nodes[target_node].node.input_types[target_port]
                if target_type != "core.any" and outgoing.type != target_type:
                    raise RuntimeGraphError(
                        f"Message {outgoing.type!r} from {stream_id!r} cannot enter "
                        f"{edge.edge.target!r}; expected {target_type!r}"
                    )
                await edge.put(outgoing.fork())

    async def _publish_eos(self, loaded: LoadedNode) -> None:
        for queues in loaded.outputs.values():
            for edge in queues:
                await edge.put(_EOS)

    def _create_run_dir(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in self.manifest.metadata.name)
        run_dir = self.run_root / f"{timestamp}-{safe_name}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def _make_report(
        self,
        run_dir: Path,
        started_ns: int,
        finished_ns: int,
        error: BaseException | None,
        close_errors: list[str],
    ) -> dict[str, Any]:
        duration_s = (finished_ns - started_ns) / 1e9
        return {
            "pipeline": self.manifest.metadata.name,
            "status": "failed" if error else "completed",
            "mode": self.manifest.runtime.mode,
            "run_dir": str(run_dir),
            "duration_seconds": duration_s,
            "error": None if error is None else f"{type(error).__name__}: {error}",
            "close_errors": close_errors,
            "nodes": {name: loaded.stats.report() for name, loaded in self.nodes.items()},
            "edges": [asdict(edge.stats) for edge in self.edges],
        }
