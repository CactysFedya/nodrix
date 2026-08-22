"""Backend-neutral graph-edge materialization.

This module joins already resolved runtime node bindings with already resolved
queue and graph-memory mechanics.

It intentionally does not know about PipelineManifest, EdgeConfig,
SystemExecutionContext, PlannedConnection, compatibility extensions, or
runtime lifecycle execution.
"""

from __future__ import annotations

from collections.abc import (
    Callable,
    Mapping,
)
from dataclasses import (
    dataclass,
    replace,
)

from .errors import RuntimeGraphError
from .memory import (
    MemoryPlan,
    MemoryRequirement,
    plan_memory,
    requirement_for_port,
)
from .runtime_components import (
    LoadedNode,
)
from .runtime_primitives import (
    RuntimeEdgeQueue,
    RuntimeQueueBinding,
)


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeEdgeBinding:
    """Resolved mechanical policy for one runtime edge."""

    queue: RuntimeQueueBinding
    memory_domain: str
    allow_copy: bool

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.queue,
            RuntimeQueueBinding,
        ):
            raise TypeError(
                "queue must be a RuntimeQueueBinding"
            )

        if (
            not isinstance(
                self.memory_domain,
                str,
            )
            or not self.memory_domain.strip()
        ):
            raise ValueError(
                "memory_domain must be a non-empty string"
            )

        if not isinstance(
            self.allow_copy,
            bool,
        ):
            raise ValueError(
                "allow_copy must be a boolean"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeGraphMemorySettings:
    """Resolved global memory mechanics used while materializing graph edges."""

    default_domain: str
    forbid_implicit_copies: bool

    def __post_init__(
        self,
    ) -> None:
        if (
            not isinstance(
                self.default_domain,
                str,
            )
            or not self.default_domain.strip()
        ):
            raise ValueError(
                "default_domain must be a non-empty string"
            )

        if not isinstance(
            self.forbid_implicit_copies,
            bool,
        ):
            raise ValueError(
                "forbid_implicit_copies must be a boolean"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeEdgeMaterialization:
    """One queue and its deterministic memory plan."""

    edge: RuntimeEdgeQueue
    memory_plan: MemoryPlan


RuntimeEdgeQueueFactory = Callable[
    [
        RuntimeQueueBinding,
        MemoryPlan,
    ],
    RuntimeEdgeQueue,
]


def runtime_types_compatible(
    source: str,
    target: str,
) -> bool:
    """Return whether two already resolved runtime port types can connect."""

    return (
        source == target
        or source == "core.any"
        or target == "core.any"
    )


def _split_endpoint(
    reference: str,
    *,
    field: str,
) -> tuple[str, str]:
    name, separator, port = (
        reference.partition(".")
    )

    if (
        not separator
        or not name
        or not port
    ):
        raise RuntimeGraphError(
            (
                f"Edge {field} must be in "
                f"node.port form: {reference!r}"
            )
        )

    return name, port


def _port_memory_requirement(
    loaded: LoadedNode,
    *,
    port: str,
    output: bool,
) -> MemoryRequirement:
    implementation = (
        getattr(
            loaded.node,
            (
                "output_memory"
                if output
                else "input_memory"
            ),
            {},
        )
        or {}
    )

    configured = (
        loaded.binding.memory_outputs
        if output
        else loaded.binding.memory_inputs
    )

    mapping = {
        **dict(
            implementation
        ),
        **dict(
            configured
        ),
    }

    requirement = requirement_for_port(
        mapping,
        port,
    )

    if loaded.binding.isolation == "process":
        return MemoryRequirement(
            ("shared",),
            preferred="shared",
        )

    return requirement


def _memory_plan(
    source: LoadedNode,
    target: LoadedNode,
    *,
    source_port: str,
    target_port: str,
    binding: RuntimeEdgeBinding,
    graph_memory: RuntimeGraphMemorySettings,
) -> MemoryPlan:
    source_requirement = (
        _port_memory_requirement(
            source,
            port=source_port,
            output=True,
        )
    )

    target_requirement = (
        _port_memory_requirement(
            target,
            port=target_port,
            output=False,
        )
    )

    allow_copy = (
        binding.allow_copy
        and not graph_memory.forbid_implicit_copies
    )

    forced_memory = (
        binding.memory_domain
    )

    if (
        forced_memory == "auto"
        and graph_memory.default_domain
        != "auto"
    ):
        forced_memory = (
            graph_memory.default_domain
        )

    memory_plan = plan_memory(
        source_requirement,
        target_requirement,
        forced=forced_memory,
        allow_copy=allow_copy,
    )

    if (
        memory_plan.adapter
        == "host_copy_to_shared"
        and target.binding.isolation
        != "process"
    ):
        memory_plan = replace(
            memory_plan,
            runtime_supported=False,
            reason=(
                "in-process CPU-to-shared "
                "conversion needs an explicit "
                "adapter node"
            ),
        )

    if (
        not memory_plan.runtime_supported
        and (
            not allow_copy
            or memory_plan.copies
        )
    ):
        raise RuntimeGraphError(
            (
                "Unsupported memory path "
                f"{binding.queue.source} -> "
                f"{binding.queue.target}: "
                f"{memory_plan.reason} "
                f"({memory_plan.source} -> "
                f"{memory_plan.target})"
            )
        )

    return memory_plan


def materialize_runtime_edge(
    nodes: Mapping[
        str,
        LoadedNode,
    ],
    binding: RuntimeEdgeBinding,
    graph_memory: RuntimeGraphMemorySettings,
    *,
    queue_factory: (
        RuntimeEdgeQueueFactory
    ) = RuntimeEdgeQueue,
) -> RuntimeEdgeMaterialization:
    """Validate, plan, construct and wire one runtime edge."""

    source_name, source_port = (
        _split_endpoint(
            binding.queue.source,
            field="source",
        )
    )

    target_name, target_port = (
        _split_endpoint(
            binding.queue.target,
            field="target",
        )
    )

    if (
        source_name not in nodes
        or target_name not in nodes
    ):
        raise RuntimeGraphError(
            (
                "Edge references unknown node: "
                f"{binding.queue.source} -> "
                f"{binding.queue.target}"
            )
        )

    source = nodes[
        source_name
    ]

    target = nodes[
        target_name
    ]

    if (
        source_port
        not in source.node.output_types
    ):
        raise RuntimeGraphError(
            "Unknown output port: "
            f"{binding.queue.source}"
        )

    if (
        target_port
        not in target.node.input_types
    ):
        raise RuntimeGraphError(
            "Unknown input port: "
            f"{binding.queue.target}"
        )

    source_type = (
        source.node.output_types[
            source_port
        ]
    )

    target_type = (
        target.node.input_types[
            target_port
        ]
    )

    if not runtime_types_compatible(
        source_type,
        target_type,
    ):
        raise RuntimeGraphError(
            (
                "Type mismatch "
                f"{binding.queue.source} "
                f"({source_type}) -> "
                f"{binding.queue.target} "
                f"({target_type})"
            )
        )

    if target_port in target.inputs:
        raise RuntimeGraphError(
            (
                "Input port already connected: "
                f"{binding.queue.target}"
            )
        )

    memory_plan = _memory_plan(
        source,
        target,
        source_port=source_port,
        target_port=target_port,
        binding=binding,
        graph_memory=graph_memory,
    )

    edge = queue_factory(
        binding.queue,
        memory_plan,
    )

    if not isinstance(
        edge,
        RuntimeEdgeQueue,
    ):
        raise TypeError(
            (
                "queue_factory must return "
                "RuntimeEdgeQueue"
            )
        )

    source.outputs[
        source_port
    ].append(
        edge
    )

    target.inputs[
        target_port
    ] = edge

    return RuntimeEdgeMaterialization(
        edge=edge,
        memory_plan=memory_plan,
    )


__all__ = [
    "RuntimeEdgeBinding",
    "RuntimeEdgeMaterialization",
    "RuntimeEdgeQueueFactory",
    "RuntimeGraphMemorySettings",
    "materialize_runtime_edge",
    "runtime_types_compatible",
]
