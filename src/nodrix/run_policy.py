"""Immutable ExecutionPolicy provenance for persistent Nodrix Runs.

policy.json records the effective cross-domain control-plane policy used for
one Run.

The document deliberately does not persist literal redaction secrets. Those
values are runtime-sensitive material, not historical provenance. Their
omission is represented explicitly so readers and comparison tools never
mistake an incomplete security projection for the original secret material.

policy.json is immutable historical evidence:

- it belongs to one RunSession and exact Plan;
- it is published once without overwrite semantics;
- JSON is finite and strict;
- publication is fsynced before linking the final name;
- literal secret values are never persisted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import (
    Any,
    Mapping,
)

from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.redaction import (
    RedactionPolicy,
)
from nodrix.run_session import (
    RunSession,
)


RUN_POLICY_V1_API_VERSION = (
    "nodrix.execution-policy/v1"
)

RUN_POLICY_API_VERSION = (
    "nodrix.execution-policy/v2"
)

RUN_POLICY_KIND = (
    "ExecutionPolicy"
)


class RunPolicyError(RuntimeError):
    """Base error for persistent execution-policy provenance."""


class RunPolicyCorruptionError(
    RunPolicyError
):
    """policy.json violates its persistence contract."""


def _reject_json_constant(
    value: str,
) -> None:
    raise ValueError(
        f"non-standard JSON constant {value!r}"
    )


def _redaction_document(
    policy: RedactionPolicy,
) -> dict[str, Any]:
    if not isinstance(
        policy,
        RedactionPolicy,
    ):
        raise TypeError(
            "redaction policy must be a RedactionPolicy"
        )

    return {
        "sensitiveKeyTokens": list(
            policy.sensitive_key_tokens
        ),
        "marker": policy.marker,
        "secretValues": {
            "configured": bool(
                policy.secrets
            ),
            "count": len(
                policy.secrets
            ),
            "persisted": False,
        },
    }


def execution_policy_document(
    policy: ExecutionPolicy,
    *,
    run_id: str,
    plan_id: str,
) -> dict[str, Any]:
    """Return the safe immutable persistence projection of a policy."""

    if not isinstance(
        policy,
        ExecutionPolicy,
    ):
        raise TypeError(
            "policy must be an ExecutionPolicy"
        )

    if not isinstance(
        run_id,
        str,
    ) or not run_id:
        raise ValueError(
            "run_id must be a non-empty string"
        )

    if not isinstance(
        plan_id,
        str,
    ) or not plan_id:
        raise ValueError(
            "plan_id must be a non-empty string"
        )

    environment = policy.environment
    logs = policy.logs
    metrics = policy.metrics

    return {
        "apiVersion": (
            RUN_POLICY_API_VERSION
        ),
        "kind": RUN_POLICY_KIND,
        "runId": run_id,
        "planId": plan_id,
        "environment": {
            "variables": list(
                environment.variables
            ),
            "redaction": (
                _redaction_document(
                    environment.redaction
                )
            ),
        },
        "logs": {
            "enabled": logs.enabled,
            "minLevel": logs.min_level,
            "categories": list(
                logs.categories
            ),
            "maxBytes": logs.max_bytes,
            "maxCategoryBytes": (
                logs.max_category_bytes
            ),
            "maxRecordBytes": (
                logs.max_record_bytes
            ),
            "overflow": logs.overflow,
            "redaction": (
                _redaction_document(
                    logs.redaction
                )
            ),
        },
        "metrics": (
            None
            if metrics is None
            else {
                "maxRecords": (
                    metrics.max_records
                ),
                "maxBytes": (
                    metrics.max_bytes
                ),
                "maxRecordBytes": (
                    metrics.max_record_bytes
                ),
                "overflow": (
                    metrics.overflow
                ),
            }
        ),
    }


def _mapping(
    value: Any,
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(
        value,
        Mapping,
    ):
        raise RunPolicyCorruptionError(
            f"{field_name} must be an object"
        )

    return value


def _string_list(
    value: Any,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if not isinstance(
        value,
        list,
    ):
        raise RunPolicyCorruptionError(
            f"{field_name} must be an array"
        )

    result: list[str] = []

    for item in value:
        if not isinstance(
            item,
            str,
        ):
            raise RunPolicyCorruptionError(
                f"{field_name} values must be strings"
            )

        result.append(
            item
        )

    return tuple(
        result
    )


def _positive_integer(
    value: Any,
    *,
    field_name: str,
) -> int:
    if (
        not isinstance(
            value,
            int,
        )
        or isinstance(
            value,
            bool,
        )
        or value <= 0
    ):
        raise RunPolicyCorruptionError(
            f"{field_name} must be a positive integer"
        )

    return value


def _validate_redaction(
    value: Any,
    *,
    field_name: str,
) -> None:
    document = _mapping(
        value,
        field_name=field_name,
    )

    expected = {
        "sensitiveKeyTokens",
        "marker",
        "secretValues",
    }

    if set(document) != expected:
        raise RunPolicyCorruptionError(
            f"{field_name} has unsupported fields"
        )

    _string_list(
        document[
            "sensitiveKeyTokens"
        ],
        field_name=(
            f"{field_name}.sensitiveKeyTokens"
        ),
    )

    marker = document[
        "marker"
    ]

    if (
        not isinstance(
            marker,
            str,
        )
        or not marker
    ):
        raise RunPolicyCorruptionError(
            f"{field_name}.marker must be a non-empty string"
        )

    secrets = _mapping(
        document[
            "secretValues"
        ],
        field_name=(
            f"{field_name}.secretValues"
        ),
    )

    if set(secrets) != {
        "configured",
        "count",
        "persisted",
    }:
        raise RunPolicyCorruptionError(
            f"{field_name}.secretValues has unsupported fields"
        )

    configured = secrets[
        "configured"
    ]
    count = secrets[
        "count"
    ]
    persisted = secrets[
        "persisted"
    ]

    if not isinstance(
        configured,
        bool,
    ):
        raise RunPolicyCorruptionError(
            f"{field_name}.secretValues.configured must be a bool"
        )

    if (
        not isinstance(
            count,
            int,
        )
        or isinstance(
            count,
            bool,
        )
        or count < 0
    ):
        raise RunPolicyCorruptionError(
            f"{field_name}.secretValues.count must be a non-negative integer"
        )

    if configured != (
        count > 0
    ):
        raise RunPolicyCorruptionError(
            f"{field_name}.secretValues configured/count mismatch"
        )

    if persisted is not False:
        raise RunPolicyCorruptionError(
            f"{field_name}.secretValues.persisted must be false"
        )


def _validate_execution_policy_document_v1(
    document: Any,
    *,
    run_id: str,
    plan_id: str,
) -> dict[str, Any]:
    if not isinstance(
        document,
        dict,
    ):
        raise RunPolicyCorruptionError(
            "policy.json must contain a JSON object"
        )

    expected = {
        "apiVersion",
        "kind",
        "runId",
        "planId",
        "environment",
        "logs",
    }

    if set(document) != expected:
        raise RunPolicyCorruptionError(
            "policy.json has unsupported fields"
        )

    if (
        document[
            "apiVersion"
        ]
        != RUN_POLICY_V1_API_VERSION
    ):
        raise RunPolicyCorruptionError(
            "policy.json apiVersion is unsupported"
        )

    if (
        document[
            "kind"
        ]
        != RUN_POLICY_KIND
    ):
        raise RunPolicyCorruptionError(
            "policy.json kind is invalid"
        )

    if (
        document[
            "runId"
        ]
        != run_id
    ):
        raise RunPolicyCorruptionError(
            "policy.json runId does not match RunSession"
        )

    if (
        document[
            "planId"
        ]
        != plan_id
    ):
        raise RunPolicyCorruptionError(
            "policy.json planId does not match RunSession"
        )

    environment = _mapping(
        document[
            "environment"
        ],
        field_name=(
            "policy.json environment"
        ),
    )

    if set(environment) != {
        "variables",
        "redaction",
    }:
        raise RunPolicyCorruptionError(
            "policy.json environment has unsupported fields"
        )

    _string_list(
        environment[
            "variables"
        ],
        field_name=(
            "policy.json environment.variables"
        ),
    )

    _validate_redaction(
        environment[
            "redaction"
        ],
        field_name=(
            "policy.json environment.redaction"
        ),
    )

    logs = _mapping(
        document[
            "logs"
        ],
        field_name="policy.json logs",
    )

    if set(logs) != {
        "enabled",
        "minLevel",
        "categories",
        "maxBytes",
        "maxCategoryBytes",
        "maxRecordBytes",
        "overflow",
        "redaction",
    }:
        raise RunPolicyCorruptionError(
            "policy.json logs has unsupported fields"
        )

    if not isinstance(
        logs[
            "enabled"
        ],
        bool,
    ):
        raise RunPolicyCorruptionError(
            "policy.json logs.enabled must be a bool"
        )

    if (
        not isinstance(
            logs[
                "minLevel"
            ],
            str,
        )
        or not logs[
            "minLevel"
        ]
    ):
        raise RunPolicyCorruptionError(
            "policy.json logs.minLevel must be a non-empty string"
        )

    _string_list(
        logs[
            "categories"
        ],
        field_name=(
            "policy.json logs.categories"
        ),
    )

    max_bytes = _positive_integer(
        logs[
            "maxBytes"
        ],
        field_name=(
            "policy.json logs.maxBytes"
        ),
    )

    max_category_bytes = (
        _positive_integer(
            logs[
                "maxCategoryBytes"
            ],
            field_name=(
                "policy.json logs.maxCategoryBytes"
            ),
        )
    )

    max_record_bytes = (
        _positive_integer(
            logs[
                "maxRecordBytes"
            ],
            field_name=(
                "policy.json logs.maxRecordBytes"
            ),
        )
    )

    if (
        max_category_bytes
        > max_bytes
    ):
        raise RunPolicyCorruptionError(
            "policy.json maxCategoryBytes cannot exceed maxBytes"
        )

    if (
        max_record_bytes
        > max_category_bytes
    ):
        raise RunPolicyCorruptionError(
            "policy.json maxRecordBytes cannot exceed maxCategoryBytes"
        )

    if (
        not isinstance(
            logs[
                "overflow"
            ],
            str,
        )
        or not logs[
            "overflow"
        ]
    ):
        raise RunPolicyCorruptionError(
            "policy.json logs.overflow must be a non-empty string"
        )

    _validate_redaction(
        logs[
            "redaction"
        ],
        field_name=(
            "policy.json logs.redaction"
        ),
    )

    return document



def validate_execution_policy_document(
    value: object,
    *,
    run_id: str,
    plan_id: str,
) -> dict[str, Any]:
    """Validate historical v1 or current v2 policy provenance."""

    if not isinstance(
        value,
        Mapping,
    ):
        raise RunPolicyCorruptionError(
            "policy.json must contain a JSON object"
        )

    document = dict(
        value
    )

    api_version = document.get(
        "apiVersion"
    )

    if (
        api_version
        == RUN_POLICY_V1_API_VERSION
    ):
        return (
            _validate_execution_policy_document_v1(
                document,
                run_id=run_id,
                plan_id=plan_id,
            )
        )

    if (
        api_version
        != RUN_POLICY_API_VERSION
    ):
        raise RunPolicyCorruptionError(
            "policy.json has unsupported apiVersion"
        )

    expected = {
        "apiVersion",
        "kind",
        "runId",
        "planId",
        "environment",
        "logs",
        "metrics",
    }

    if set(document) != expected:
        raise RunPolicyCorruptionError(
            "policy.json has invalid fields"
        )

    # Reuse the complete historical validation for every unchanged field.
    legacy_document = dict(
        document
    )
    metrics = legacy_document.pop(
        "metrics"
    )
    legacy_document[
        "apiVersion"
    ] = RUN_POLICY_V1_API_VERSION

    _validate_execution_policy_document_v1(
        legacy_document,
        run_id=run_id,
        plan_id=plan_id,
    )

    if metrics is None:
        return document

    if not isinstance(
        metrics,
        Mapping,
    ):
        raise RunPolicyCorruptionError(
            "policy.json metrics must be "
            "a JSON object or null"
        )

    metric_document = dict(
        metrics
    )

    expected_metrics = {
        "maxRecords",
        "maxBytes",
        "maxRecordBytes",
        "overflow",
    }

    if (
        set(metric_document)
        != expected_metrics
    ):
        raise RunPolicyCorruptionError(
            "policy.json metrics has invalid fields"
        )

    for field_name in (
        "maxRecords",
        "maxBytes",
        "maxRecordBytes",
    ):
        field_value = metric_document[
            field_name
        ]

        if (
            isinstance(
                field_value,
                bool,
            )
            or not isinstance(
                field_value,
                int,
            )
            or field_value <= 0
        ):
            raise RunPolicyCorruptionError(
                "policy.json metrics."
                f"{field_name} must be "
                "a positive integer"
            )

    if (
        metric_document[
            "maxRecordBytes"
        ]
        > metric_document[
            "maxBytes"
        ]
    ):
        raise RunPolicyCorruptionError(
            "policy.json metrics.maxRecordBytes "
            "cannot exceed metrics.maxBytes"
        )

    if (
        metric_document[
            "overflow"
        ]
        != "drop"
    ):
        raise RunPolicyCorruptionError(
            "policy.json metrics.overflow "
            "must be 'drop'"
        )

    return document


class RunPolicyStore:
    """Immutable policy.json storage bound to one RunSession."""

    def __init__(
        self,
        session: RunSession,
        *,
        policy: ExecutionPolicy,
    ) -> None:
        if not isinstance(
            session,
            RunSession,
        ):
            raise TypeError(
                "session must be a RunSession"
            )

        if not isinstance(
            policy,
            ExecutionPolicy,
        ):
            raise TypeError(
                "policy must be an ExecutionPolicy"
            )

        self._session = session
        self._policy = policy
        self.path = (
            session.directory
            / "policy.json"
        )

    @property
    def run_id(
        self,
    ) -> str:
        return self._session.run_id

    @property
    def plan_id(
        self,
    ) -> str:
        return self._session.plan_id

    @property
    def policy(
        self,
    ) -> ExecutionPolicy:
        return self._policy

    def document(
        self,
    ) -> dict[str, Any]:
        return execution_policy_document(
            self._policy,
            run_id=self.run_id,
            plan_id=self.plan_id,
        )

    def read(
        self,
    ) -> dict[str, Any] | None:
        if not self.path.exists():
            return None

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
            raise RunPolicyCorruptionError(
                "policy.json contains invalid JSON"
            ) from exc

        return validate_execution_policy_document(
            document,
            run_id=self.run_id,
            plan_id=self.plan_id,
        )

    def create(
        self,
    ) -> dict[str, Any]:
        """Publish policy.json once without replacement semantics."""

        document = self.document()

        # Validate the exact serialized projection before touching storage.
        validate_execution_policy_document(
            document,
            run_id=self.run_id,
            plan_id=self.plan_id,
        )

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

        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.path.parent,
                prefix=".policy.",
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

            # Hard-link publication is atomic and never replaces
            # an already existing historical policy.json.
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
    "RUN_POLICY_API_VERSION",
    "RUN_POLICY_V1_API_VERSION",
    "RUN_POLICY_KIND",
    "RunPolicyCorruptionError",
    "RunPolicyError",
    "RunPolicyStore",
    "execution_policy_document",
    "validate_execution_policy_document",
]
