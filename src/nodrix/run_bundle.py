"""Validated immutable evidence bundle for one persisted canonical Run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .run_policy import (
    load_run_policy,
)
from .run_record import (
    RunRecordStore,
)
from .run_session import (
    RUN_LAYOUT_SCHEMA,
    RunSession,
    load_run_session,
)
from .run_snapshots import (
    DEFINITION_SNAPSHOT,
    PLAN_SNAPSHOT,
    RunSnapshotStore,
)


class CanonicalRunBundleError(
    RuntimeError
):
    """Base error for canonical persisted Run bundles."""


class CanonicalRunBundleIncompleteError(
    CanonicalRunBundleError
):
    """Required immutable Run evidence is missing."""


def _freeze_json(
    value: Any,
) -> Any:
    if isinstance(
        value,
        dict,
    ):
        return MappingProxyType(
            {
                key: _freeze_json(
                    item
                )
                for key, item
                in value.items()
            }
        )

    if isinstance(
        value,
        list,
    ):
        return tuple(
            _freeze_json(
                item
            )
            for item in value
        )

    return value


def _freeze_document(
    value: Mapping[str, Any],
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(
        value,
        Mapping,
    ):
        raise TypeError(
            f"{field_name} must be a mapping"
        )

    return MappingProxyType(
        {
            key: _freeze_json(
                item
            )
            for key, item
            in value.items()
        }
    )


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalRunBundle:
    """Immutable validated persisted evidence for one terminal Run."""

    session: RunSession
    run: Mapping[str, Any]
    definition: Mapping[str, Any]
    plan: Mapping[str, Any]
    policy: Mapping[str, Any] | None

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.session,
            RunSession,
        ):
            raise TypeError(
                "session must be a RunSession"
            )

        for field_name in (
            "run",
            "definition",
            "plan",
        ):
            document = getattr(
                self,
                field_name,
            )

            object.__setattr__(
                self,
                field_name,
                _freeze_document(
                    document,
                    field_name=field_name,
                ),
            )

        if self.policy is not None:
            object.__setattr__(
                self,
                "policy",
                _freeze_document(
                    self.policy,
                    field_name="policy",
                ),
            )

    @property
    def run_id(
        self,
    ) -> str:
        return self.session.run_id

    @property
    def plan_id(
        self,
    ) -> str:
        return self.session.plan_id

    @property
    def policy_available(
        self,
    ) -> bool:
        return self.policy is not None


def load_canonical_run_bundle(
    directory: str | Path,
) -> CanonicalRunBundle:
    """Load immutable evidence required to compare one terminal canonical Run."""

    session = load_run_session(
        directory
    )

    run_document = (
        RunRecordStore(
            session
        ).read()
    )

    if run_document is None:
        raise CanonicalRunBundleIncompleteError(
            "canonical Run has no final run.json"
        )

    snapshots = RunSnapshotStore(
        session
    )

    definition = snapshots.read(
        DEFINITION_SNAPSHOT
    )

    if definition is None:
        raise CanonicalRunBundleIncompleteError(
            "canonical Run has no definition.json"
        )

    plan = snapshots.read(
        PLAN_SNAPSHOT
    )

    if plan is None:
        raise CanonicalRunBundleIncompleteError(
            "canonical Run has no plan.json"
        )

    policy = load_run_policy(
        session
    )

    # policy.json became mandatory immutable provenance in layout v2.
    # Historical v1 Runs remain readable and explicitly expose policy=None.
    if (
        session.layout
        == RUN_LAYOUT_SCHEMA
        and policy is None
    ):
        raise CanonicalRunBundleIncompleteError(
            "canonical Run layout v2 has no policy.json"
        )

    return CanonicalRunBundle(
        session=session,
        run=run_document,
        definition=definition,
        plan=plan,
        policy=policy,
    )


__all__ = [
    "CanonicalRunBundle",
    "CanonicalRunBundleError",
    "CanonicalRunBundleIncompleteError",
    "load_canonical_run_bundle",
]
