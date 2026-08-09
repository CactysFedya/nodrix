from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from plyctl import compile_package, load_package_definition


def _write_package(tmp_path: Path, *, namespace: str | None = None) -> tuple[Path, str, str]:
    suffix = uuid4().hex[:8]
    module_root = f"demo_pkg_{suffix}"
    package_namespace = namespace or f"semantic_{suffix}"
    root = tmp_path / "package"
    source = root / "src" / module_root
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'''[project]
name = "demo-dist-{suffix}"
version = "1.2.3"
description = "Package SDK test"
''',
        encoding="utf-8",
    )
    (root / "nodrix.yaml").write_text(
        f'''apiVersion: nodrix.dev/v1
package:
  namespace: {package_namespace}
discover:
  modules:
    - {module_root}.components
''',
        encoding="utf-8",
    )
    (source / "components.py").write_text(
        '''from dataclasses import dataclass
from plyctl import Resource, message, node, resource

@message
@dataclass(frozen=True)
class Frame:
    value: int

@resource
def cache(capacity: int = 4):
    yield {"capacity": capacity}

@node
class Processor:
    def __init__(self, cache: Resource[dict], gain: float = 1.5):
        self.cache = cache
        self.gain = gain

    def process(self, frame: Frame) -> Frame:
        return Frame(int(frame.value * self.gain))
''',
        encoding="utf-8",
    )
    return root, module_root, package_namespace


def _drop_modules(module_root: str) -> None:
    for name in list(sys.modules):
        if name == module_root or name.startswith(module_root + "."):
            sys.modules.pop(name, None)


def test_load_definition_uses_pyproject_version_without_importing(tmp_path: Path) -> None:
    root, module_root, namespace = _write_package(tmp_path)
    components = root / "src" / module_root / "components.py"
    components.write_text("raise RuntimeError('must not import')\n", encoding="utf-8")
    definition = load_package_definition(root)
    assert definition.namespace == namespace
    assert definition.version == "1.2.3"
    assert definition.name.startswith("demo-dist-")
    assert definition.modules == (f"{module_root}.components",)


def test_package_version_cannot_be_duplicated(tmp_path: Path) -> None:
    root, _, _ = _write_package(tmp_path)
    manifest = root / "nodrix.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "package:\n", "package:\n  version: 9.9.9\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must not be duplicated"):
        load_package_definition(root)


def test_compile_package_builds_provider_api_from_decorators(tmp_path: Path) -> None:
    root, module_root, namespace = _write_package(tmp_path)
    try:
        compiled = compile_package(root)
        assert compiled.provider_manifest.metadata.id == namespace
        assert compiled.provider_manifest.metadata.version == "1.2.3"
        assert compiled.provider_manifest.metadata.provider_api == "2"
        assert compiled.provider_manifest.schema == "plyctl-provider/2"
        assert [item.id for item in compiled.provider_manifest.nodes] == [f"{namespace}.processor"]
        assert [item.id for item in compiled.provider_manifest.resources] == [f"{namespace}.cache"]
        assert [item.id for item in compiled.messages] == [f"{namespace}.frame/v1"]
        node = compiled.provider_manifest.nodes[0]
        assert node.inputs == {"frame": f"{namespace}.frame/v1"}
        assert node.outputs == {"output": f"{namespace}.frame/v1"}
        assert node.bindings == {"cache": "resource"}
        assert node.parameters_schema["properties"]["gain"] == {
            "type": "number",
            "default": 1.5,
        }
        resource = compiled.provider_manifest.resources[0]
        assert resource.parameters_schema["properties"]["capacity"] == {
            "type": "integer",
            "default": 4,
        }
        assert set(compiled.provider_runtime.nodes) == {f"{namespace}.processor"}
        assert set(compiled.provider_runtime.resources) == {f"{namespace}.cache"}
    finally:
        _drop_modules(module_root)


def test_package_namespace_overrides_python_module_root(tmp_path: Path) -> None:
    root, module_root, _ = _write_package(tmp_path, namespace="mapping.semantic")
    try:
        compiled = compile_package(root)
        assert compiled.provider_manifest.nodes[0].id == "mapping.semantic.processor"
        assert compiled.provider_manifest.resources[0].id == "mapping.semantic.cache"
        assert compiled.messages[0].id == "mapping.semantic.frame/v1"
    finally:
        _drop_modules(module_root)


def test_static_metadata_is_json_serializable(tmp_path: Path) -> None:
    root, module_root, namespace = _write_package(tmp_path)
    try:
        compiled = compile_package(root)
        rendered = json.dumps(compiled.to_static_metadata(), sort_keys=True)
        assert namespace in rendered
        assert "processor" in rendered
        assert "frame/v1" in rendered
    finally:
        _drop_modules(module_root)


def test_compile_can_be_repeated_when_module_has_same_namespace(tmp_path: Path) -> None:
    root, module_root, namespace = _write_package(tmp_path)
    try:
        first = compile_package(root)
        second = compile_package(root)
        assert first.provider_manifest.to_dict() == second.provider_manifest.to_dict()
        assert set(second.provider_runtime.nodes) == {f"{namespace}.processor"}
    finally:
        _drop_modules(module_root)


def test_invalid_namespace_is_rejected_before_discovery(tmp_path: Path) -> None:
    root, _, namespace = _write_package(tmp_path)
    manifest = root / "nodrix.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            f"namespace: {namespace}", "namespace: Bad Namespace"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="lowercase dotted identifier"):
        load_package_definition(root)
