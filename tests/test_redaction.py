from __future__ import annotations

from nodrix.redaction import (
    DEFAULT_REDACTION_MARKER,
    RedactionPolicy,
)


def test_sensitive_mapping_keys_are_redacted() -> None:
    policy = RedactionPolicy()

    result = policy.redact(
        {
            "username": "robot",
            "password": "very-secret",
            "nested": {
                "api_token": "abc123",
                "mode": "fast",
            },
        }
    )

    assert (
        result["username"]
        == "robot"
    )

    assert (
        result["password"]
        == DEFAULT_REDACTION_MARKER
    )

    assert (
        result["nested"]["api_token"]
        == DEFAULT_REDACTION_MARKER
    )

    assert (
        result["nested"]["mode"]
        == "fast"
    )


def test_explicit_secret_is_removed_from_arbitrary_text() -> None:
    policy = RedactionPolicy(
        secrets=(
            "super-secret-value",
        )
    )

    result = policy.redact_text(
        "connection failed for super-secret-value"
    )

    assert (
        "super-secret-value"
        not in result
    )

    assert (
        DEFAULT_REDACTION_MARKER
        in result
    )


def test_longer_secret_is_redacted_before_shorter_secret() -> None:
    policy = RedactionPolicy(
        secrets=(
            "secret",
            "secret-value",
        )
    )

    result = policy.redact_text(
        "secret-value"
    )

    assert (
        result
        == DEFAULT_REDACTION_MARKER
    )


def test_redaction_preserves_non_sensitive_structure() -> None:
    policy = RedactionPolicy()

    result = policy.redact(
        {
            "items": (
                1,
                "hello",
                {
                    "enabled": True,
                },
            ),
        }
    )

    assert result == {
        "items": [
            1,
            "hello",
            {
                "enabled": True,
            },
        ],
    }
