from __future__ import annotations

from pathlib import Path

import yaml

from nodrix.workspace import (
    create_workspace,
    find_workspace,
    resolve_pipeline_reference,
    set_active_context,
)


def _pipeline(path: Path, name: str) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema": "nodrix.pipeline/v2",
                "metadata": {"name": name},
                "runtime": {"mode": "batch"},
                "nodes": {},
                "edges": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_workspace_discovery_alias_and_default(tmp_path: Path) -> None:
    root = tmp_path / "project"
    create_workspace(root)
    _pipeline(root / "pipelines/main.yaml", "main")
    nested = root / "configs/a/b"
    nested.mkdir(parents=True)

    assert find_workspace(nested) == root
    resolved = resolve_pipeline_reference(start=nested)
    assert resolved.root == root
    assert resolved.pipeline == (root / "pipelines/main.yaml").resolve()
    assert resolved.pipeline_name == "main"
    assert resolved.context_name == "local"
    assert resolved.view == "compact"


def test_context_state_overrides_default(tmp_path: Path) -> None:
    root = tmp_path / "project"
    create_workspace(root)
    _pipeline(root / "pipelines/main.yaml", "main")
    project_file = root / "nodrix.yaml"
    config = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    config["contexts"]["sim"] = {
        "environment": "local",
        "profile": "default",
        "view": "operations",
    }
    project_file.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )

    set_active_context(root, "sim")
    resolved = resolve_pipeline_reference(start=root)
    assert resolved.context_name == "sim"
    assert resolved.view == "operations"


def test_explicit_pipeline_inside_workspace_does_not_activate_context(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    create_workspace(root)
    pipeline = root / "pipelines/direct.yaml"
    _pipeline(pipeline, "direct")

    config_path = root / "nodrix.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["defaults"]["context"] = "robot"
    config["contexts"]["robot"] = {
        "environment": "missing-ros",
        "profile": "default",
    }
    config["environments"]["missing-ros"] = {
        "shell": {
            "source": ["/definitely/missing/ros/setup.bash"],
        },
    }
    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )

    resolved = resolve_pipeline_reference(str(pipeline), start=root)

    assert resolved.pipeline == pipeline.resolve()
    assert resolved.context_name is None
    assert resolved.environment_name is None
    assert resolved.sources == ()


def test_direct_pipeline_works_without_workspace(tmp_path: Path) -> None:
    pipeline = tmp_path / "custom.yaml"
    _pipeline(pipeline, "custom")
    resolved = resolve_pipeline_reference(pipeline, start=tmp_path)
    assert resolved.config_path is None
    assert resolved.pipeline == pipeline.resolve()
