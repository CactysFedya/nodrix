from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nodrix.benchmark_canonical import (
    benchmark_plan_digest,
)
from nodrix.benchmark_operation import (
    benchmark_subject,
)
from nodrix.benchmarking import (
    BenchmarkPlan,
    BenchmarkVariant,
)
from nodrix.pipeline_definition import (
    pipeline_entity_ref,
    pipeline_source_definition_record,
    pipeline_source_digest,
    pipeline_source_identity,
    pipeline_source_revision_ref,
)


def _write_pipeline(
    path: Path,
    content: str = "name: demo\n",
) -> Path:
    path.write_bytes(
        content.encode("utf-8")
    )

    return path


def _benchmark_plan(
    pipeline: Path,
) -> BenchmarkPlan:
    return BenchmarkPlan(
        pipeline=pipeline,
        repeat=2,
        warmup=1,
        variants=(
            BenchmarkVariant(
                "fast",
                "maximum-throughput",
                (
                    "detector.imgsz=320",
                ),
                (),
            ),
        ),
    )


def test_pipeline_source_digest_is_exact_raw_file_sha256(
    tmp_path: Path,
) -> None:
    pipeline = _write_pipeline(
        tmp_path / "pipeline.yaml",
        "name: demo\n# comment\n",
    )

    expected = hashlib.sha256(
        pipeline.read_bytes()
    ).hexdigest()

    assert (
        pipeline_source_digest(
            pipeline
        )
        == expected
    )


def test_pipeline_source_revision_is_format_sensitive(
    tmp_path: Path,
) -> None:
    pipeline = _write_pipeline(
        tmp_path / "pipeline.yaml",
        "name: demo\n",
    )

    first = (
        pipeline_source_revision_ref(
            pipeline
        )
    )

    pipeline.write_text(
        "name: demo   \n",
        encoding="utf-8",
    )

    second = (
        pipeline_source_revision_ref(
            pipeline
        )
    )

    assert first.entity == second.entity
    assert first != second


def test_pipeline_entity_identity_preserves_legacy_workspace_stem_policy(
    tmp_path: Path,
) -> None:
    pipeline = _write_pipeline(
        tmp_path / "mapping-fast.yaml"
    )

    assert (
        pipeline_entity_ref(
            pipeline
        ).canonical
        == (
            "nodrix://pipeline/"
            "workspace/mapping-fast"
        )
    )


def test_pipeline_source_definition_record_uses_exact_source_revision(
    tmp_path: Path,
) -> None:
    pipeline = _write_pipeline(
        tmp_path / "pipeline.yaml",
        """
apiVersion: plyctl.dev/v2
kind: Pipeline
name: demo
""".lstrip(),
    )

    record = (
        pipeline_source_definition_record(
            pipeline
        )
    )

    entity, revision = (
        pipeline_source_identity(
            pipeline
        )
    )

    assert record.entity == entity
    assert record.revision == revision

    assert (
        record.definition
        == pipeline.read_bytes()
    )

    assert (
        record.schema
        == "plyctl.dev/v2"
    )


def test_pipeline_source_definition_uses_existing_default_api_version(
    tmp_path: Path,
) -> None:
    pipeline = _write_pipeline(
        tmp_path / "pipeline.yaml",
        "name: demo\n",
    )

    record = (
        pipeline_source_definition_record(
            pipeline
        )
    )

    assert (
        record.schema
        == "plyctl.dev/v1"
    )


def test_pipeline_source_definition_does_not_resolve_blocks(
    tmp_path: Path,
) -> None:
    pipeline = _write_pipeline(
        tmp_path / "pipeline.yaml",
        """
name: demo
blocks:
  missing: does-not-exist.yaml
""".lstrip(),
    )

    record = (
        pipeline_source_definition_record(
            pipeline
        )
    )

    assert (
        record.revision.digest
        == pipeline_source_digest(
            pipeline
        )
    )


def test_benchmark_subject_reuses_pipeline_source_identity(
    tmp_path: Path,
) -> None:
    pipeline = _write_pipeline(
        tmp_path / "pipeline.yaml"
    )

    plan = _benchmark_plan(
        pipeline
    )

    expected = (
        pipeline_source_identity(
            pipeline
        )
    )

    assert (
        benchmark_subject(plan)
        == expected
    )


def test_benchmark_plan_digest_preserves_legacy_raw_pipeline_policy(
    tmp_path: Path,
) -> None:
    pipeline = _write_pipeline(
        tmp_path / "pipeline.yaml"
    )

    plan = _benchmark_plan(
        pipeline
    )

    document = {
        "pipeline_sha256": (
            hashlib.sha256(
                pipeline.read_bytes()
            ).hexdigest()
        ),
        "repeat": 2,
        "warmup": 1,
        "variants": [
            {
                "name": "fast",
                "profile": (
                    "maximum-throughput"
                ),
                "set": [
                    "detector.imgsz=320"
                ],
                "block": [],
            },
        ],
    }

    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    expected = hashlib.sha256(
        encoded
    ).hexdigest()

    assert (
        benchmark_plan_digest(
            plan
        )
        == expected
    )


def test_same_pipeline_source_in_different_locations_has_same_revision_identity(
    tmp_path: Path,
) -> None:
    first_root = (
        tmp_path / "first"
    )

    second_root = (
        tmp_path / "second"
    )

    first_root.mkdir()
    second_root.mkdir()

    content = (
        "name: demo\n"
    )

    first = _write_pipeline(
        first_root / "pipeline.yaml",
        content,
    )

    second = _write_pipeline(
        second_root / "pipeline.yaml",
        content,
    )

    first_record = (
        pipeline_source_definition_record(
            first
        )
    )

    second_record = (
        pipeline_source_definition_record(
            second
        )
    )

    assert (
        first_record.entity
        == second_record.entity
    )

    assert (
        first_record.revision
        == second_record.revision
    )

    assert (
        first_record.metadata[
            "source_path"
        ]
        != second_record.metadata[
            "source_path"
        ]
    )
