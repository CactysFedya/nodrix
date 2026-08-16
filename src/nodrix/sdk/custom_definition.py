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
    Operation,
    OperationKind,
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

    def operation(
        self,
        kind: (
            str
            | OperationKind
        ),
        *,
        parameters: (
            Mapping[str, Any]
            | None
        ) = None,
        pin_revision: bool = True,
    ) -> Operation:
        """Author one canonical Operation over this Definition.

        When ``pin_revision`` is true, the Operation targets the exact
        immutable Definition revision currently represented by this authoring
        object.

        Set ``pin_revision=False`` when revision resolution should be deferred
        to a future planner or definition resolver.

        This method only authors intent.  It does not plan, execute, dispatch,
        persist, or select an Executor.
        """

        if not isinstance(
            pin_revision,
            bool,
        ):
            raise TypeError(
                "pin_revision must be a boolean"
            )

        if pin_revision:
            record = (
                custom_definition_record(
                    self._document
                )
            )

            subject = record.entity
            revision = record.revision
        else:
            subject = (
                custom_definition_entity_ref(
                    self._document
                )
            )

            revision = None

        return Operation(
            kind=kind,
            subject=subject,
            subject_revision=revision,
            parameters=(
                {}
                if parameters is None
                else parameters
            ),
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
