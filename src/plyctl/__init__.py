"""Plyctl public SDK.

``nodrix`` remains an import-compatible alias throughout the 2.x series.
"""

from __future__ import annotations

from ._aliases import install_package_alias, mirror_public_api


_nodrix = install_package_alias(__name__, "nodrix")
mirror_public_api(globals(), _nodrix)

PlyctlError = _nodrix.NodrixError

__all__ = [*getattr(_nodrix, "__all__", ()), "PlyctlError"]
