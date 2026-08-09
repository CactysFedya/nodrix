from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nodrix.cli import app
from nodrix.local_dev import (
    activate_local_project,
    compile_local_project,
    reset_local_development_modules,
)
from nodrix.provider_common import ProviderPolicy
from nodrix.provider_loading import (
    load_provider,
    load_provider_node,
    load_provider_resource,
    reset_provider_cache,
)
from nodrix.registry import load_node_class, reset_file_module_cache


@pytest.fixture(autouse=True)
def _reset_development_state():
    reset_local_development_modules()
    reset_provider_cache()
    reset_file_module_cache()
    yield
    reset_local_development_modules()
    reset_provider_cache()
    reset_file_module_cache()


def _write_local_project(root: Path) -> None:
    components = root / "components"
    components.mkdir(parents=True)
    suffix = "".join(ch if ch.isalnum() else "_" for ch in root.name)
    message_class = f"Ping_{suffix}"
    (components / "types.py").write_text(
        "from dataclasses import dataclass\n"
        "from plyctl import message\n\n"
        "@message\n"
        "@dataclass(frozen=True)\n"
        f"class {message_class}:\n"
        "    value: int\n",
        encoding="utf-8",
    )
    (components / "main.py").write_text(
        "from plyctl import node, resource\n"
        f"from components.types import {message_class}\n\n"
        "@resource\n"
        "def cache(seed: int = 0):\n"
        "    yield {'seed': seed}\n\n"
        "@node\n"
        f"def echo(message: {message_class}) -> {message_class}:\n"
        "    return message\n",
        encoding="utf-8",
    )


def test_local_components_compile_to_reserved_namespace(tmp_path: Path) -> None:
    _write_local_project(tmp_path)

    project = compile_local_project(tmp_path)

    assert project.namespace == "local"
    assert project.package_mode is False
    assert [item.id for item in project.compiled.provider_manifest.nodes] == ["local.echo"]
    assert [item.id for item in project.compiled.provider_manifest.resources] == ["local.cache"]
    assert len(project.compiled.messages) == 1
    assert project.compiled.messages[0].id.startswith("local.ping_")
    assert project.compiled.messages[0].id.endswith("/v1")


def test_development_provider_resolves_local_node_and_resource(tmp_path: Path) -> None:
    _write_local_project(tmp_path)
    project = compile_local_project(tmp_path)

    with activate_local_project(project):
        node_cls = load_provider_node("local.echo")
        resource_cls = load_provider_resource("local.cache")
        assert node_cls is project.compiled.provider_runtime.nodes["local.echo"]
        assert resource_cls is project.compiled.provider_runtime.resources["local.cache"]

    assert load_provider_node("local.echo") is None
    assert load_provider_resource("local.cache") is None


def test_development_provider_is_rejected_in_production(tmp_path: Path) -> None:
    _write_local_project(tmp_path)
    project = compile_local_project(tmp_path)

    with activate_local_project(project):
        with pytest.raises(Exception, match="not available in production"):
            load_provider("local", policy=ProviderPolicy(production=True))


def test_local_module_name_collision_is_rejected(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_local_project(first)
    _write_local_project(second)

    compile_local_project(first)
    with pytest.raises(RuntimeError, match="already resolves"):
        compile_local_project(second)


def test_same_physical_file_reference_reuses_node_class_identity(tmp_path: Path) -> None:
    path = tmp_path / "shared.py"
    path.write_text(
        "from nodrix.node import Node\n\n"
        "class Shared(Node):\n"
        "    pass\n",
        encoding="utf-8",
    )

    relative = load_node_class("shared.py:Shared", base_dir=tmp_path)
    absolute = load_node_class(f"{path}:Shared", base_dir=tmp_path)

    assert relative is absolute


def test_check_cli_discovers_local_components(tmp_path: Path) -> None:
    _write_local_project(tmp_path)

    result = CliRunner().invoke(app, ["check", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "OK" in result.output
    assert "local" in result.output
    assert "1 nodes" in result.output
    assert "1 resources" in result.output
    assert "1 messages" in result.output


def test_dev_inspect_cli_lists_component_ids(tmp_path: Path) -> None:
    _write_local_project(tmp_path)

    result = CliRunner().invoke(app, ["dev", "inspect", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "local.echo" in result.output
    assert "local.cache" in result.output
    assert "local.ping_" in result.output
