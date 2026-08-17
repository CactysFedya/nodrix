from __future__ import annotations

from pathlib import Path

from nodrix.system import (
    load_system_details,
    plan_system,
)
from nodrix.system.definition import system_definition_digest


def _write(
    path: Path,
    text: str,
) -> Path:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        text,
        encoding="utf-8",
    )

    return path


def test_composed_and_configured_source_has_canonical_system_identity(
    tmp_path: Path,
) -> None:
    module_path = _write(
        tmp_path / "modules/platform.yaml",
        """schema: nodrix.system-module/v1

targets:
  - name: pi5
    kind: host
    properties: "${config.platform}"
""",
    )

    config_path = _write(
        tmp_path / "config/defaults.yaml",
        """platform:
  backend: local
  os: linux
  architecture: aarch64
""",
    )

    composed_path = _write(
        tmp_path / "systems/composed.yaml",
        """apiVersion: nodrix.system/v1
kind: System
name: robot

imports:
  - ../modules/platform.yaml

config:
  - ../config/defaults.yaml
""",
    )

    monolithic_path = _write(
        tmp_path / "systems/monolithic.yaml",
        """apiVersion: nodrix.system/v1
kind: System
name: robot

targets:
  - name: pi5
    kind: host
    properties:
      backend: local
      os: linux
      architecture: aarch64
""",
    )

    composed = load_system_details(
        composed_path
    )

    monolithic = load_system_details(
        monolithic_path
    )

    # Authoring layout and provenance differ.
    assert composed.resolution.module_sources == (
        module_path.resolve(),
    )

    assert composed.resolution.config_sources == (
        config_path.resolve(),
    )

    assert monolithic.resolution.module_sources == ()
    assert monolithic.resolution.config_sources == ()

    # Authoring-only concepts disappear before the canonical boundary.
    assert "imports" not in composed.canonical
    assert "config" not in composed.canonical
    assert "resolution" not in composed.canonical

    # Different authoring layouts resolve to one canonical System.
    assert composed.canonical == monolithic.canonical
    assert composed.system == monolithic.system

    # Canonical Definition identity depends on resolved semantics only.
    assert (
        system_definition_digest(
            composed.system
        )
        == system_definition_digest(
            monolithic.system
        )
    )

    # Planning observes the same canonical System identity as well.
    composed_plan = plan_system(
        composed.system
    )

    monolithic_plan = plan_system(
        monolithic.system
    )

    assert (
        composed_plan.system_sha256
        == monolithic_plan.system_sha256
    )

    assert (
        composed_plan.system_sha256
        == system_definition_digest(
            composed.system
        )
    )
