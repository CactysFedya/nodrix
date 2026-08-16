"""Python authoring frontend for user-defined Nodrix Definition kinds."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from ..custom_definition import (
    custom_definition_entity_ref,
    custom_definition_record,
    normalize_custom_definition,
)
from ..model import (
    DefinitionRecord,
    EntityRef,
)


class CustomDefinition:
    """Author one user-defined canonical Nodrix Definition.

    This class is an authoring frontend only.

    It does not plan, execute, persist, discover, or store Definitions.
    """

    def __init__(
        self,
        *,
        kind: str,
        namespace: str,
        name: str,
        schema: str,
        spec: (
            Mapping[str, Any]
            | None
        ) = None,
    ) -> None:
        self._document = (
            normalize_custom_definition(
                {
                    "apiVersion": schema,
                    "kind": kind,
                    "metadata": {
                        "namespace": namespace,
                        "name": name,
                    },
                    "spec": dict(
                        spec or {}
                    ),
                }
            )
        )

    @property
    def kind(self) -> str:
        return str(
            self._document["kind"]
        )

    @property
    def namespace(self) -> str:
        metadata = self._document[
            "metadata"
        ]

        return str(
            metadata["namespace"]
        )

    @property
    def name(self) -> str:
        metadata = self._document[
            "metadata"
        ]

        return str(
            metadata["name"]
        )

    @property
    def schema(self) -> str:
        return str(
            self._document[
                "apiVersion"
            ]
        )

    @property
    def spec(
        self,
    ) -> Mapping[str, Any]:
        return deepcopy(
            self._document["spec"]
        )

    def to_dict(
        self,
    ) -> dict[str, Any]:
        """Return the canonical custom Definition document."""

        return deepcopy(
            self._document
        )

    def entity_ref(
        self,
    ) -> EntityRef:
        """Return this Definition's canonical logical identity."""

        return (
            custom_definition_entity_ref(
                self._document
            )
        )

    def definition_record(
        self,
        *,
        metadata: (
            Mapping[str, Any]
            | None
        ) = None,
    ) -> DefinitionRecord:
        """Compile this authoring object into DefinitionRecord."""

        return custom_definition_record(
            self._document,
            record_metadata=metadata,
        )


__all__ = [
    "CustomDefinition",
]
