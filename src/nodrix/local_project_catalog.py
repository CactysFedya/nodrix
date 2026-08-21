"""Build backend-neutral System DefinitionCatalog from a local SDK project.

This module owns local-development package discovery.  Planning consumers see
only DefinitionCatalog and never depend on CLI presentation code.

Local development modules are always reset before and after compilation because
multiple projects may be resolved inside one long-lived Python process.
"""

from __future__ import annotations

from pathlib import Path
import sys

from .local_dev import (
    compile_local_project,
    reset_local_development_modules,
)
from .sdk.definitions import (
    MessageDefinition,
    NodeDefinition,
    ResourceDefinition,
)
from .system import (
    DefinitionCatalog,
)


def local_project_definition_catalog(
    path: str | Path,
) -> DefinitionCatalog:
    """Compile one local SDK project into neutral planner definitions."""

    root = (
        Path(
            path
        )
        .expanduser()
        .resolve()
    )

    reset_local_development_modules()

    try:
        project = compile_local_project(
            root
        )

        nodes: dict[
            str,
            NodeDefinition,
        ] = {}

        resources: dict[
            str,
            ResourceDefinition,
        ] = {}

        messages: dict[
            str,
            MessageDefinition,
        ] = {}

        for cls in (
            project
            .compiled
            .provider_runtime
            .nodes
            .values()
        ):
            definition = getattr(
                cls,
                "__plyctl_definition__",
                None,
            )

            if isinstance(
                definition,
                NodeDefinition,
            ):
                nodes[
                    definition.name
                ] = definition

        for cls in (
            project
            .compiled
            .provider_runtime
            .resources
            .values()
        ):
            definition = getattr(
                cls,
                "__plyctl_definition__",
                None,
            )

            if isinstance(
                definition,
                ResourceDefinition,
            ):
                resources[
                    definition.name
                ] = definition

        # Message definitions may live anywhere in compiled local modules.
        # Read them before cleanup; the immutable definition objects remain
        # valid after module removal.
        for module_name in (
            project.module_names
        ):
            module = sys.modules.get(
                module_name
            )

            if module is None:
                continue

            for value in vars(
                module
            ).values():
                definition = getattr(
                    value,
                    "__plyctl_definition__",
                    None,
                )

                if isinstance(
                    definition,
                    MessageDefinition,
                ):
                    messages[
                        definition.type_id
                    ] = definition

        return DefinitionCatalog(
            nodes=nodes,
            resources=resources,
            messages=messages,
        )

    finally:
        reset_local_development_modules()


__all__ = [
    "local_project_definition_catalog",
]
