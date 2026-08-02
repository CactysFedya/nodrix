"""Public Plyctl names and compatibility identifiers.

The ``nodrix`` values are protocol identifiers from releases before the
project rename. They remain supported for the complete 2.x series so existing
manifests and providers continue to work unchanged.
"""

from __future__ import annotations


PRODUCT_NAME = "Plyctl"
CLI_NAME = "plyctl"

MANIFEST_API_V1 = "plyctl.dev/v1"
MANIFEST_API_V2 = "plyctl.dev/v2"
LEGACY_MANIFEST_API_V1 = "nodrix.dev/v1"
LEGACY_MANIFEST_API_V2 = "nodrix.dev/v2"

SUPPORTED_MANIFEST_API_VERSIONS = frozenset(
    {
        MANIFEST_API_V1,
        MANIFEST_API_V2,
        LEGACY_MANIFEST_API_V1,
        LEGACY_MANIFEST_API_V2,
    }
)
MANIFEST_API_V2_VERSIONS = frozenset(
    {MANIFEST_API_V2, LEGACY_MANIFEST_API_V2}
)


def is_manifest_v2(value: str) -> bool:
    """Return whether *value* selects either spelling of Manifest API v2."""

    return value in MANIFEST_API_V2_VERSIONS


__all__ = [
    "CLI_NAME",
    "LEGACY_MANIFEST_API_V1",
    "LEGACY_MANIFEST_API_V2",
    "MANIFEST_API_V1",
    "MANIFEST_API_V2",
    "MANIFEST_API_V2_VERSIONS",
    "PRODUCT_NAME",
    "SUPPORTED_MANIFEST_API_VERSIONS",
    "is_manifest_v2",
]
