"""Canonical project storage layout.

This module owns the canonical mapping from one project root to Nodrix storage
locations.

StorageLayout is path policy only. It does not create directories, write
files, move data, resolve canonical identities, or own retention.

Architectural boundary:

    canonical identity
        !=
    physical storage location

Materialized project data lives outside ``.nodrix``:

    datasets/
    artifacts/

Nodrix-managed state, history and generated state live under:

    .nodrix/

Legacy ``outputs/`` remains addressable for compatibility but is not a new
canonical materialized-data root.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StorageLayout:
    """Canonical filesystem layout rooted at one Nodrix project."""

    project_root: Path

    def __post_init__(self) -> None:
        try:
            normalized = (
                Path(self.project_root)
                .expanduser()
                .resolve()
            )
        except TypeError as exc:
            raise TypeError(
                "project_root must be a path-like value"
            ) from exc

        object.__setattr__(
            self,
            "project_root",
            normalized,
        )

    @property
    def managed_root(self) -> Path:
        """Return the Nodrix-managed state root."""

        return self.project_root / ".nodrix"

    @property
    def runs_root(self) -> Path:
        """Return durable and legacy-compatible Run storage."""

        return self.managed_root / "runs"

    @property
    def logs_root(self) -> Path:
        """Return Nodrix-managed runtime log storage."""

        return self.managed_root / "logs"

    @property
    def operations_root(self) -> Path:
        """Return engineering-operation history storage."""

        return self.managed_root / "operations"

    @property
    def benchmarks_root(self) -> Path:
        """Return benchmark history and evidence storage."""

        return self.managed_root / "benchmarks"

    @property
    def optimization_root(self) -> Path:
        """Return optimization history and evidence storage."""

        return self.managed_root / "optimization"

    @property
    def build_root(self) -> Path:
        """Return Nodrix-managed build state."""

        return self.managed_root / "build"

    @property
    def prefix_root(self) -> Path:
        """Return Nodrix-managed installation prefixes."""

        return self.managed_root / "prefix"

    @property
    def generated_root(self) -> Path:
        """Return generated Nodrix state and scaffolding."""

        return self.managed_root / "generated"

    @property
    def cache_root(self) -> Path:
        """Return disposable Nodrix-managed cache storage."""

        return self.managed_root / "cache"

    @property
    def workflow_cache_root(self) -> Path:
        """Return workflow step-cache state."""

        return self.cache_root / "workflows"

    @property
    def native_build_root(self) -> Path:
        """Return the compatibility native runtime build directory."""

        return self.managed_root / "native-build"

    @property
    def system_generated_root(self) -> Path:
        """Return generated compatibility System manifests."""

        return self.managed_root / "system-generated"

    @property
    def context_file(self) -> Path:
        """Return the active workspace-context state file."""

        return self.managed_root / "context"

    @property
    def shell_rc_file(self) -> Path:
        """Return the generated workspace shell configuration."""

        return self.managed_root / "shell.rc"

    @property
    def supervisor_file(self) -> Path:
        """Return runtime supervisor state."""

        return self.managed_root / "supervisor.json"

    @property
    def datasets_root(self) -> Path:
        """Return canonical project materialized Dataset storage."""

        return self.project_root / "datasets"

    @property
    def artifacts_root(self) -> Path:
        """Return canonical project materialized Artifact storage."""

        return self.project_root / "artifacts"

    @property
    def legacy_outputs_root(self) -> Path:
        """Return the compatibility root for existing ``outputs/`` data."""

        return self.project_root / "outputs"


__all__ = [
    "StorageLayout",
]
