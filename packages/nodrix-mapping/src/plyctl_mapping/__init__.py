"""Canonical Plyctl Mapping import path."""

from plyctl._aliases import install_package_alias, mirror_public_api


_legacy = install_package_alias(__name__, "nodrix_mapping")
mirror_public_api(globals(), _legacy)
__all__ = list(getattr(_legacy, "__all__", ()))
