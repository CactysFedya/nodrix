"""Immutable provenance snapshots attached to one persistent Nodrix Run.

Run snapshots preserve the exact canonical inputs that explain why one
Execution happened as it did.

The storage layer is deliberately execution-domain neutral.  A System,
Workflow, benchmark planner, or future custom execution domain may construct
its own versioned snapshot content while RunSnapshotStore provides:

- association with one Run and Plan;
- deterministic JSON serialization;
- atomic publication;
- create-once / never-overwrite semantics.

Currently standardized snapshot kinds are:

- definition -> definition.json
- plan       -> plan.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from nodrix.run_session import RunSession


RUN_SNAPSHOT_API_VERSION = "nodrix.run-snapshot/v1"
RUN_SNAPSHOT_KIND = "RunSnapshot"

DEFINITION_SNAPSHOT = "definition"
PLAN_SNAPSHOT = "plan"

_SNAPSHOT_FILES = {
    DEFINITION_SNAPSHOT: "definition.json",
    PLAN_SNAPSHOT: "plan.json",
}


class RunSnapshotError(RuntimeError):
    """Base error for immutable Run provenance snapshots."""


class RunSnapshotCorruptionError(
    RunSnapshotError
):
    """A persisted Run snapshot violates its storage contract."""


def _snapshot_kind(
    value: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            "snapshot_kind must be a string"
        )

    normalized = value.strip()

    if normalized not in _SNAPSHOT_FILES:
        allowed = ", ".join(
            sorted(_SNAPSHOT_FILES)
        )
        raise ValueError(
            "unsupported snapshot_kind "
            f"{value!r}; expected one of: {allowed}"
        )

    return normalized


def _json_content(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(
        value,
        Mapping,
    ):
        raise TypeError(
            "snapshot content must be a mapping"
        )

    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "snapshot content must contain only "
            "finite JSON-compatible values"
        ) from exc

    decoded = json.loads(
        encoded
    )

    if not isinstance(
        decoded,
        dict,
    ):
        raise TypeError(
            "snapshot content must serialize "
            "to a JSON object"
        )

    return decoded


class RunSnapshotStore:
    """Publish immutable Definition and Plan snapshots for one Run."""

    def __init__(
        self,
        session: RunSession,
    ) -> None:
        if not isinstance(
            session,
            RunSession,
        ):
            raise TypeError(
                "session must be a RunSession"
            )

        self._session = session

    @property
    def run_id(self) -> str:
        return self._session.run_id

    @property
    def plan_id(self) -> str:
        return self._session.plan_id

    def path(
        self,
        snapshot_kind: str,
    ) -> Path:
        canonical_kind = (
            _snapshot_kind(
                snapshot_kind
            )
        )

        return (
            self._session.directory
            / _SNAPSHOT_FILES[
                canonical_kind
            ]
        )

    def _validate_document(
        self,
        document: Any,
        *,
        snapshot_kind: str,
    ) -> dict[str, Any]:
        canonical_kind = (
            _snapshot_kind(
                snapshot_kind
            )
        )

        if not isinstance(
            document,
            dict,
        ):
            raise RunSnapshotCorruptionError(
                "Run snapshot must contain "
                "a JSON object"
            )

        if (
            document.get("apiVersion")
            != RUN_SNAPSHOT_API_VERSION
        ):
            raise RunSnapshotCorruptionError(
                "unsupported Run snapshot apiVersion"
            )

        if (
            document.get("kind")
            != RUN_SNAPSHOT_KIND
        ):
            raise RunSnapshotCorruptionError(
                "invalid Run snapshot kind"
            )

        if (
            document.get("snapshotKind")
            != canonical_kind
        ):
            raise RunSnapshotCorruptionError(
                "Run snapshot kind does not "
                "match its filename"
            )

        if (
            document.get("runId")
            != self.run_id
        ):
            raise RunSnapshotCorruptionError(
                "Run snapshot belongs to "
                "a different Run"
            )

        if (
            document.get("planId")
            != self.plan_id
        ):
            raise RunSnapshotCorruptionError(
                "Run snapshot belongs to "
                "a different Plan"
            )

        content = document.get(
            "content"
        )

        if not isinstance(
            content,
            dict,
        ):
            raise RunSnapshotCorruptionError(
                "Run snapshot content must "
                "be an object"
            )

        return document

    def read(
        self,
        snapshot_kind: str,
    ) -> dict[str, Any] | None:
        """Read and validate one immutable snapshot."""

        canonical_kind = (
            _snapshot_kind(
                snapshot_kind
            )
        )

        path = self.path(
            canonical_kind
        )

        if not path.exists():
            return None

        if not path.is_file():
            raise RunSnapshotCorruptionError(
                f"{path.name} exists but "
                "is not a file"
            )

        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as stream:
                document = json.load(
                    stream
                )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RunSnapshotCorruptionError(
                f"{path.name} contains invalid JSON"
            ) from exc

        return self._validate_document(
            document,
            snapshot_kind=canonical_kind,
        )

    def create(
        self,
        snapshot_kind: str,
        content: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically publish one snapshot exactly once."""

        canonical_kind = (
            _snapshot_kind(
                snapshot_kind
            )
        )

        canonical_content = (
            _json_content(
                content
            )
        )

        document = {
            "apiVersion": (
                RUN_SNAPSHOT_API_VERSION
            ),
            "kind": (
                RUN_SNAPSHOT_KIND
            ),
            "snapshotKind": (
                canonical_kind
            ),
            "runId": self.run_id,
            "planId": self.plan_id,
            "content": (
                canonical_content
            ),
        }

        encoded = (
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode(
            "utf-8"
        )

        path = self.path(
            canonical_kind
        )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=(
                    f".{canonical_kind}."
                ),
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(
                    stream.name
                )

                stream.write(
                    encoded
                )
                stream.flush()
                os.fsync(
                    stream.fileno()
                )

            # Hard-link publication gives us atomic create-without-overwrite.
            os.link(
                temporary_path,
                path,
            )
        finally:
            if (
                temporary_path
                is not None
            ):
                try:
                    temporary_path.unlink(
                        missing_ok=True
                    )
                except OSError:
                    pass

        return document


__all__ = [
    "DEFINITION_SNAPSHOT",
    "PLAN_SNAPSHOT",
    "RUN_SNAPSHOT_API_VERSION",
    "RUN_SNAPSHOT_KIND",
    "RunSnapshotCorruptionError",
    "RunSnapshotError",
    "RunSnapshotStore",
]
