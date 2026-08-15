from __future__ import annotations

from pathlib import Path

from nodrix.cv_types import TYPE_REGISTRY
from nodrix.local_dev import compile_local_project, reset_local_development_modules


def _write_project(root: Path, value: int) -> None:
    components = root / "components"
    components.mkdir(parents=True)
    (components / "types.py").write_text(
        "from dataclasses import dataclass\n"
        "from plyctl import message\n\n"
        "@message\n"
        "@dataclass(frozen=True)\n"
        "class Frame:\n"
        "    value: int\n",
        encoding="utf-8",
    )
    (components / "nodes.py").write_text(
        "from plyctl import node\n"
        "from components.types import Frame\n\n"
        "@node\n"
        "def source() -> Frame:\n"
        f"    return Frame({value})\n",
        encoding="utf-8",
    )


def test_reset_local_development_modules_unregisters_local_messages(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_project(first, 1)
    _write_project(second, 2)

    reset_local_development_modules()
    try:
        compile_local_project(first)
        first_definition = TYPE_REGISTRY.definition("local.frame/v1")
        assert first_definition is not None

        reset_local_development_modules()
        assert TYPE_REGISTRY.definition("local.frame/v1") is None

        compile_local_project(second)
        second_definition = TYPE_REGISTRY.definition("local.frame/v1")
        assert second_definition is not None
        assert second_definition.payload_type is not first_definition.payload_type
    finally:
        reset_local_development_modules()

    assert TYPE_REGISTRY.definition("local.frame/v1") is None
