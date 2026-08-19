"""Domain-neutral redaction for Nodrix persistent records and logs.

Redaction is intentionally independent from System, Workflow, backends and
logging.  The same policy can protect environment snapshots, structured logs,
future metrics metadata and diagnostic records.

The default policy protects values whose field names look credential-related.
Additional literal secret values may be supplied by the caller and are removed
from arbitrary strings as well.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_REDACTION_MARKER = "[REDACTED]"

DEFAULT_SENSITIVE_KEY_TOKENS = (
    "accesskey",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "passwd",
    "privatekey",
    "secret",
    "token",
)


def _normalized_key(
    value: str,
) -> str:
    return "".join(
        character.lower()
        for character in value
        if character.isalnum()
    )


@dataclass(frozen=True, slots=True)
class RedactionPolicy:
    """Immutable policy for protecting structured values and text."""

    sensitive_key_tokens: tuple[str, ...] = (
        DEFAULT_SENSITIVE_KEY_TOKENS
    )
    secrets: tuple[str, ...] = ()
    marker: str = DEFAULT_REDACTION_MARKER

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.marker,
            str,
        ):
            raise TypeError(
                "redaction marker must be a string"
            )

        marker = self.marker.strip()

        if not marker:
            raise ValueError(
                "redaction marker must be non-empty"
            )

        tokens: list[str] = []

        for value in self.sensitive_key_tokens:
            if not isinstance(
                value,
                str,
            ):
                raise TypeError(
                    "sensitive key tokens must be strings"
                )

            normalized = _normalized_key(
                value
            )

            if not normalized:
                raise ValueError(
                    "sensitive key token must be non-empty"
                )

            if normalized not in tokens:
                tokens.append(
                    normalized
                )

        secrets: list[str] = []

        for value in self.secrets:
            if not isinstance(
                value,
                str,
            ):
                raise TypeError(
                    "redaction secrets must be strings"
                )

            if not value:
                raise ValueError(
                    "redaction secret must be non-empty"
                )

            if value not in secrets:
                secrets.append(
                    value
                )

        # Longest first prevents a shorter secret from partially masking a
        # longer one and leaving a recognizable suffix.
        secrets.sort(
            key=len,
            reverse=True,
        )

        object.__setattr__(
            self,
            "marker",
            marker,
        )

        object.__setattr__(
            self,
            "sensitive_key_tokens",
            tuple(tokens),
        )

        object.__setattr__(
            self,
            "secrets",
            tuple(secrets),
        )

    def key_is_sensitive(
        self,
        key: str,
    ) -> bool:
        if not isinstance(
            key,
            str,
        ):
            raise TypeError(
                "redaction key must be a string"
            )

        normalized = _normalized_key(
            key
        )

        return any(
            token in normalized
            for token
            in self.sensitive_key_tokens
        )

    def redact_text(
        self,
        value: str,
    ) -> str:
        if not isinstance(
            value,
            str,
        ):
            raise TypeError(
                "redacted text must be a string"
            )

        result = value

        for secret in self.secrets:
            result = result.replace(
                secret,
                self.marker,
            )

        return result

    def redact(
        self,
        value: Any,
        *,
        key: str | None = None,
    ) -> Any:
        """Return a JSON-friendly recursively redacted value."""

        if (
            key is not None
            and self.key_is_sensitive(
                key
            )
        ):
            return self.marker

        if isinstance(
            value,
            str,
        ):
            return self.redact_text(
                value
            )

        if value is None or isinstance(
            value,
            (
                bool,
                int,
                float,
            ),
        ):
            return value

        if isinstance(
            value,
            Mapping,
        ):
            result: dict[str, Any] = {}

            for item_key, item in value.items():
                if not isinstance(
                    item_key,
                    str,
                ):
                    raise TypeError(
                        "redacted mapping keys "
                        "must be strings"
                    )

                result[item_key] = (
                    self.redact(
                        item,
                        key=item_key,
                    )
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
                self.redact(
                    item
                )
                for item in value
            ]

        raise TypeError(
            "redaction contains unsupported "
            f"value {type(value).__name__}"
        )


__all__ = [
    "DEFAULT_REDACTION_MARKER",
    "DEFAULT_SENSITIVE_KEY_TOKENS",
    "RedactionPolicy",
]
