from __future__ import annotations

from pathlib import Path

from nodrix.system.io import (
    SystemLoadResult,
    load_system_details,
    loads_system,
    system_to_canonical,
)


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


def test_single_system_reports_only_root_source(
    tmp_path: Path,
) -> None:
    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n",
    )

    details = load_system_details(
        system_path
    )

    assert details.resolution.sources == (
        system_path.resolve(),
    )
    assert (
        details.resolution.module_sources
        == ()
    )
    assert (
        details.resolution.config_sources
        == ()
    )
    assert (
        details.resolution.config_provenance
        == {}
    )


def test_resolution_details_separate_modules_and_config(
    tmp_path: Path,
) -> None:
    module = _write(
        tmp_path / "modules/target.yaml",
        "schema: nodrix.system-module/v1\n"
        "targets:\n"
        "  - name: pi5\n"
        "    kind: host\n"
        "    properties:\n"
        '      threads: "${config.runtime.threads}"\n',
    )

    config = _write(
        tmp_path / "config/defaults.yaml",
        "runtime:\n"
        "  threads: 4\n",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "imports:\n"
        "  - modules/target.yaml\n"
        "config:\n"
        "  - config/defaults.yaml\n",
    )

    details = load_system_details(
        system_path
    )

    assert details.resolution.sources == (
        system_path.resolve(),
        module.resolve(),
        config.resolve(),
    )

    assert details.resolution.module_sources == (
        module.resolve(),
    )

    assert details.resolution.config_sources == (
        config.resolve(),
    )

    assert details.resolution.source_for_config(
        "runtime.threads"
    ) == config.resolve()

    assert (
        details.system.targets[0]
        .properties["threads"]
        == 4
    )


def test_system_load_result_keeps_backward_compatible_default_resolution(
    tmp_path: Path,
) -> None:
    system = loads_system(
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
    )

    result = SystemLoadResult(
        system=system,
        canonical=system_to_canonical(
            system
        ),
        path=tmp_path / "system.yaml",
        format="yaml",
    )

    assert result.resolution.sources == ()
    assert result.resolution.module_sources == ()
    assert result.resolution.config_sources == ()
    assert result.resolution.config_provenance == {}


def test_resolution_details_do_not_enter_canonical_document(
    tmp_path: Path,
) -> None:
    config = _write(
        tmp_path / "config.yaml",
        "runtime:\n"
        "  threads: 4\n",
    )

    system_path = _write(
        tmp_path / "system.yaml",
        "apiVersion: nodrix.system/v1\n"
        "kind: System\n"
        "name: robot\n"
        "config: [config.yaml]\n"
        "metadata:\n"
        '  threads: "${config.runtime.threads}"\n',
    )

    details = load_system_details(
        system_path
    )

    assert details.resolution.config_sources == (
        config.resolve(),
    )

    assert "resolution" not in details.canonical
    assert "config" not in details.canonical
    assert "imports" not in details.canonical
