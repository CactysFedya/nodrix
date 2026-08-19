"""Immutable runtime-environment provenance for persistent Nodrix Runs.

The default environment snapshot is deliberately minimal.

Nodrix never persists the complete process environment implicitly. Environment
variables are captured only through an explicit allowlist because arbitrary
process environments frequently contain credentials, tokens and user-specific
paths.

The snapshot is provenance, not live status:

- it is created once;
- it is fsynced before publication;
- it is atomically published without overwrite semantics;
- it can be protected by the shared RedactionPolicy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import tempfile
from typing import Any, Mapping

from nodrix.redaction import (
    RedactionPolicy,
)
from nodrix.run_session import (
    RunSession,
)


RUN_ENVIRONMENT_API_VERSION = (
    "nodrix.run-environment/v1"
)

RUN_ENVIRONMENT_KIND = (
    "RunEnvironment"
)


class RunEnvironmentError(RuntimeError):
    """Base error for persistent Run environment provenance."""


class RunEnvironmentCorruptionError(
    RunEnvironmentError
):
    """environment.json violates its persistence contract."""


def _timestamp_text(
    value: datetime,
) -> str:
    if not isinstance(
        value,
        datetime,
    ):
        raise TypeError(
            "captured_at must be a datetime"
        )

    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            "captured_at must be timezone-aware"
        )

    return (
        value
        .astimezone(timezone.utc)
        .isoformat(
            timespec="microseconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


def _parse_timestamp(
    value: Any,
) -> datetime:
    if not isinstance(
        value,
        str,
    ):
        raise RunEnvironmentCorruptionError(
            "environment capturedAt must be a string"
        )

    candidate = (
        value[:-1] + "+00:00"
        if value.endswith("Z")
        else value
    )

    try:
        result = datetime.fromisoformat(
            candidate
        )
    except ValueError as exc:
        raise RunEnvironmentCorruptionError(
            "environment capturedAt is invalid"
        ) from exc

    if (
        result.tzinfo is None
        or result.utcoffset() is None
    ):
        raise RunEnvironmentCorruptionError(
            "environment capturedAt must be timezone-aware"
        )

    return result


def _environment_name(
    value: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            "environment variable name must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            "environment variable name must be non-empty"
        )

    if (
        "=" in normalized
        or "\x00" in normalized
    ):
        raise ValueError(
            "environment variable name contains "
            "an unsupported character"
        )

    return normalized


def _json_value(
    value: Any,
) -> Any:
    if value is None or isinstance(
        value,
        (
            bool,
            int,
            str,
        ),
    ):
        return value

    if isinstance(
        value,
        float,
    ):
        if not math.isfinite(
            value
        ):
            raise ValueError(
                "environment provenance cannot contain "
                "non-finite floats"
            )

        return value

    if isinstance(
        value,
        Path,
    ):
        return str(value)

    if isinstance(
        value,
        Mapping,
    ):
        result: dict[str, Any] = {}

        for key, item in value.items():
            if not isinstance(
                key,
                str,
            ):
                raise TypeError(
                    "environment provenance mapping "
                    "keys must be strings"
                )

            result[key] = _json_value(
                item
            )

        return result

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        return [
            _json_value(
                item
            )
            for item in value
        ]

    raise TypeError(
        "environment provenance contains unsupported "
        f"value {type(value).__name__}"
    )


def _reject_json_constant(
    value: str,
) -> None:
    raise ValueError(
        f"invalid JSON numeric constant {value}"
    )


@dataclass(frozen=True, slots=True)
class RunEnvironmentPolicy:
    """Policy controlling environment provenance captured for one Run."""

    variables: tuple[str, ...] = ()
    redaction: RedactionPolicy = field(
        default_factory=RedactionPolicy
    )

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.redaction,
            RedactionPolicy,
        ):
            raise TypeError(
                "redaction must be a RedactionPolicy"
            )

        variables: list[str] = []

        for value in self.variables:
            name = _environment_name(
                value
            )

            if name not in variables:
                variables.append(
                    name
                )

        # Variable ordering is not semantic. Canonical ordering makes the
        # persisted policy deterministic.
        variables.sort()

        object.__setattr__(
            self,
            "variables",
            tuple(variables),
        )


class RunEnvironmentStore:
    """Create/read one immutable environment.json for a persistent Run."""

    def __init__(
        self,
        session: RunSession,
        *,
        policy: RunEnvironmentPolicy | None = None,
    ) -> None:
        if not isinstance(
            session,
            RunSession,
        ):
            raise TypeError(
                "session must be a RunSession"
            )

        if policy is None:
            policy = (
                RunEnvironmentPolicy()
            )

        if not isinstance(
            policy,
            RunEnvironmentPolicy,
        ):
            raise TypeError(
                "policy must be a RunEnvironmentPolicy or None"
            )

        self._session = session
        self._policy = policy

    @property
    def run_id(self) -> str:
        return self._session.run_id

    @property
    def plan_id(self) -> str:
        return self._session.plan_id

    @property
    def policy(
        self,
    ) -> RunEnvironmentPolicy:
        return self._policy

    @property
    def path(self) -> Path:
        return (
            self._session.directory
            / "environment.json"
        )

    def _validate_document(
        self,
        document: Any,
    ) -> dict[str, Any]:
        if not isinstance(
            document,
            dict,
        ):
            raise RunEnvironmentCorruptionError(
                "environment.json must contain "
                "a JSON object"
            )

        if (
            document.get(
                "apiVersion"
            )
            != RUN_ENVIRONMENT_API_VERSION
        ):
            raise RunEnvironmentCorruptionError(
                "unsupported environment.json apiVersion"
            )

        if (
            document.get("kind")
            != RUN_ENVIRONMENT_KIND
        ):
            raise RunEnvironmentCorruptionError(
                "invalid environment.json kind"
            )

        if (
            document.get("runId")
            != self.run_id
        ):
            raise RunEnvironmentCorruptionError(
                "environment.json belongs to "
                "a different Run"
            )

        if (
            document.get("planId")
            != self.plan_id
        ):
            raise RunEnvironmentCorruptionError(
                "environment.json belongs to "
                "a different Plan"
            )

        _parse_timestamp(
            document.get(
                "capturedAt"
            )
        )

        runtime = document.get(
            "runtime"
        )

        if not isinstance(
            runtime,
            dict,
        ):
            raise RunEnvironmentCorruptionError(
                "environment runtime must be an object"
            )

        variables = document.get(
            "variables"
        )

        if not isinstance(
            variables,
            dict,
        ):
            raise RunEnvironmentCorruptionError(
                "environment variables must be an object"
            )

        policy = document.get(
            "policy"
        )

        if not isinstance(
            policy,
            dict,
        ):
            raise RunEnvironmentCorruptionError(
                "environment policy must be an object"
            )

        expected_variables = list(
            self._policy.variables
        )

        if (
            policy.get(
                "variables"
            )
            != expected_variables
        ):
            raise RunEnvironmentCorruptionError(
                "environment policy variables do not "
                "match the requested capture policy"
            )

        if (
            sorted(
                variables
            )
            != expected_variables
        ):
            raise RunEnvironmentCorruptionError(
                "environment variable snapshot does not "
                "match its capture policy"
            )

        if not isinstance(
            document.get("extra"),
            dict,
        ):
            raise RunEnvironmentCorruptionError(
                "environment extra must be an object"
            )

        return document

    def read(
        self,
    ) -> dict[str, Any] | None:
        if not self.path.exists():
            return None

        if not self.path.is_file():
            raise RunEnvironmentCorruptionError(
                "environment.json exists but "
                "is not a file"
            )

        try:
            with self.path.open(
                "r",
                encoding="utf-8",
            ) as stream:
                document = json.load(
                    stream,
                    parse_constant=(
                        _reject_json_constant
                    ),
                )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            raise RunEnvironmentCorruptionError(
                "environment.json contains invalid JSON"
            ) from exc

        return self._validate_document(
            document
        )

    def capture(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        captured_at: datetime | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Capture and publish environment provenance exactly once."""

        source_environment: Mapping[
            str,
            str,
        ] = (
            os.environ
            if environ is None
            else environ
        )

        if not isinstance(
            source_environment,
            Mapping,
        ):
            raise TypeError(
                "environ must be a mapping or None"
            )

        timestamp = (
            datetime.now(
                timezone.utc
            )
            if captured_at is None
            else captured_at
        )

        variables: dict[str, Any] = {}

        for name in self._policy.variables:
            raw = source_environment.get(
                name
            )

            if (
                raw is not None
                and not isinstance(
                    raw,
                    str,
                )
            ):
                raise TypeError(
                    "environment values must be strings"
                )

            variables[name] = (
                None
                if raw is None
                else self._policy.redaction.redact(
                    raw,
                    key=name,
                )
            )

        canonical_extra = (
            {}
            if extra is None
            else self._policy.redaction.redact(
                extra
            )
        )

        if not isinstance(
            canonical_extra,
            Mapping,
        ):
            raise TypeError(
                "environment extra must be a mapping"
            )

        document = {
            "apiVersion": (
                RUN_ENVIRONMENT_API_VERSION
            ),
            "kind": (
                RUN_ENVIRONMENT_KIND
            ),
            "runId": self.run_id,
            "planId": self.plan_id,
            "capturedAt": (
                _timestamp_text(
                    timestamp
                )
            ),
            "runtime": {
                "os": (
                    platform.system()
                ),
                "osRelease": (
                    platform.release()
                ),
                "architecture": (
                    platform.machine()
                ),
                "pythonImplementation": (
                    platform.python_implementation()
                ),
                "pythonVersion": (
                    platform.python_version()
                ),
            },
            "variables": (
                _json_value(
                    variables
                )
            ),
            "extra": (
                _json_value(
                    canonical_extra
                )
            ),
            "policy": {
                "variables": list(
                    self._policy.variables
                ),
                "redaction": {
                    "marker": (
                        self._policy
                        .redaction
                        .marker
                    ),
                    "sensitiveKeyTokens": list(
                        self._policy
                        .redaction
                        .sensitive_key_tokens
                    ),
                    "explicitSecretCount": len(
                        self._policy
                        .redaction
                        .secrets
                    ),
                },
            },
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

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.path.parent,
                prefix=".environment.",
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

            # Immutable provenance: publish once, never replace.
            os.link(
                temporary_path,
                self.path,
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
    "RUN_ENVIRONMENT_API_VERSION",
    "RUN_ENVIRONMENT_KIND",
    "RunEnvironmentCorruptionError",
    "RunEnvironmentError",
    "RunEnvironmentPolicy",
    "RunEnvironmentStore",
]
