from pathlib import Path

import pytest
import yaml

from nodrix.model import (
    EntityRef,
)
from nodrix.project_canonical import (
    project_definition_digest,
    project_definition_record,
    project_entity_ref,
    project_revision_ref,
)


def _write_project(
    root: Path,
    *,
    name: str = "robot",
    extra: dict[str, object] | None = None,
) -> Path:
    document: dict[
        str,
        object,
    ] = {
        "schema": "nodrix.project/v1",
        "name": name,
        "defaults": {
            "context": "local",
        },
    }

    if extra:
        document.update(
            extra
        )

    path = (
        root / "nodrix.yaml"
    )

    path.write_text(
        yaml.safe_dump(
            document,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    return path


def test_project_definition_record_reuses_existing_identity(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path
    )

    record = (
        project_definition_record(
            tmp_path
        )
    )

    assert (
        record.entity
        == project_entity_ref(
            tmp_path
        )
    )

    assert (
        record.revision
        == project_revision_ref(
            tmp_path
        )
    )


def test_project_definition_record_uses_project_schema(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path
    )

    record = (
        project_definition_record(
            tmp_path
        )
    )

    assert (
        record.schema
        == "nodrix.project/v1"
    )

    assert (
        record.definition[
            "name"
        ]
        == "robot"
    )


def test_project_definition_record_preserves_existing_digest(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path
    )

    record = (
        project_definition_record(
            tmp_path
        )
    )

    assert (
        record.revision.digest
        == project_definition_digest(
            tmp_path
        )
    )


def test_project_definition_identity_uses_workspace_namespace(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path
    )

    record = (
        project_definition_record(
            tmp_path
        )
    )

    assert (
        record.entity.canonical
        == (
            "nodrix://project/"
            "workspace/robot"
        )
    )


def test_project_definition_supports_custom_namespace(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path
    )

    record = (
        project_definition_record(
            tmp_path,
            namespace=(
                "organization/acme"
            ),
        )
    )

    assert (
        record.entity
        == EntityRef(
            kind="project",
            namespace=(
                "organization/acme"
            ),
            name="robot",
        )
    )

    assert (
        record.revision.entity
        == record.entity
    )


def test_project_metadata_does_not_change_revision(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path
    )

    first = (
        project_definition_record(
            tmp_path,
            metadata={
                "origin": "first",
            },
        )
    )

    second = (
        project_definition_record(
            tmp_path,
            metadata={
                "origin": "second",
            },
        )
    )

    assert (
        first.revision
        == second.revision
    )


def test_project_source_path_is_metadata_only(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path
    )

    record = (
        project_definition_record(
            tmp_path
        )
    )

    assert (
        record.metadata[
            "source_path"
        ]
        == str(
            (
                tmp_path
                / "nodrix.yaml"
            ).resolve()
        )
    )

    assert (
        "source_path"
        not in record.definition
    )


def test_project_definition_requires_schema(
    tmp_path: Path,
) -> None:
    (
        tmp_path
        / "nodrix.yaml"
    ).write_text(
        yaml.safe_dump(
            {
                "name": "robot",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            "must declare a non-empty "
            "project schema"
        ),
    ):
        project_definition_record(
            tmp_path
        )


def test_project_definition_digest_remains_mapping_order_independent(
    tmp_path: Path,
) -> None:
    first = (
        tmp_path / "first"
    )

    second = (
        tmp_path / "second"
    )

    first.mkdir()
    second.mkdir()

    (
        first / "nodrix.yaml"
    ).write_text(
        """
schema: nodrix.project/v1
name: robot
defaults:
  context: local
""".strip()
        + "\n",
        encoding="utf-8",
    )

    (
        second / "nodrix.yaml"
    ).write_text(
        """
defaults:
  context: local
name: robot
schema: nodrix.project/v1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    assert (
        project_definition_digest(
            first
        )
        == project_definition_digest(
            second
        )
    )
