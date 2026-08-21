"""Canonical Artifact materialization for Benchmark Result documents.

Benchmark Result semantic identity and Artifact content identity are distinct:

* ``BenchmarkResultIdentity`` identifies result semantics;
* ``ArtifactRecord.revision`` identifies exact persisted payload bytes.

The logical Artifact entity is stable for one Benchmark Plan + variant, while
different measured Run sets become immutable revisions of that same entity.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .benchmark_result import (
    BENCHMARK_AGGREGATION_METHOD,
    BENCHMARK_RESULT_API_VERSION,
    CanonicalBenchmarkResult,
    validate_benchmark_result_document,
)
from .materialized_storage import (
    artifact_revision_directory,
    materialize_artifact,
)
from .model import (
    ArtifactRecord,
    EntityRef,
)


BENCHMARK_RESULT_ARTIFACT_KIND = (
    "benchmark.result"
)

BENCHMARK_RESULT_MEDIA_TYPE = (
    "application/vnd.nodrix.benchmark-result+json"
)

BENCHMARK_RESULT_ARTIFACT_ENTITY_SCHEMA = (
    "nodrix.benchmark-result-artifact-entity/v1"
)


def _canonical_json_bytes(
    document: Mapping[str, Any],
    *,
    trailing_newline: bool,
) -> bytes:
    text = json.dumps(
        dict(document),
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        allow_nan=False,
    )

    if trailing_newline:
        text += "\n"

    return text.encode(
        "utf-8"
    )


def _reject_json_constant(
    value: str,
) -> None:
    raise ValueError(
        "non-finite JSON constants are not allowed: "
        f"{value}"
    )


def benchmark_result_bytes(
    result: CanonicalBenchmarkResult,
) -> bytes:
    """Return the exact canonical Artifact payload bytes."""

    if not isinstance(
        result,
        CanonicalBenchmarkResult,
    ):
        raise TypeError(
            "result must be a CanonicalBenchmarkResult"
        )

    document = result.to_dict()

    # Validate before materializing so the Artifact boundary never persists a
    # malformed Benchmark Result produced by an accidental internal mutation.
    validate_benchmark_result_document(
        document
    )

    return _canonical_json_bytes(
        document,
        trailing_newline=True,
    )


def benchmark_result_artifact_entity(
    result: CanonicalBenchmarkResult,
) -> EntityRef:
    """Return stable logical Artifact identity for one Plan + variant.

    Measured Run IDs deliberately do not participate here.  Repeating the same
    Benchmark Plan/variant produces a new immutable revision of the same
    logical result Artifact.
    """

    if not isinstance(
        result,
        CanonicalBenchmarkResult,
    ):
        raise TypeError(
            "result must be a CanonicalBenchmarkResult"
        )

    identity_document = {
        "schema": (
            BENCHMARK_RESULT_ARTIFACT_ENTITY_SCHEMA
        ),
        "benchmarkPlanId": (
            result.benchmark_plan_id
        ),
        "variant": (
            result.variant.to_dict()
        ),
    }

    digest = hashlib.sha256(
        _canonical_json_bytes(
            identity_document,
            trailing_newline=False,
        )
    ).hexdigest()

    return EntityRef(
        kind="artifact",
        namespace="project",
        name=(
            "benchmark-result-"
            + digest[:24]
        ),
    )


def benchmark_result_artifact_metadata(
    result: CanonicalBenchmarkResult,
) -> dict[str, object]:
    """Return compact searchable metadata outside Artifact identity."""

    if not isinstance(
        result,
        CanonicalBenchmarkResult,
    ):
        raise TypeError(
            "result must be a CanonicalBenchmarkResult"
        )

    return {
        "benchmarkResultApiVersion": (
            BENCHMARK_RESULT_API_VERSION
        ),
        "benchmarkResultIdentity": (
            result.identity.value
        ),
        "benchmarkPlanId": (
            result.benchmark_plan_id
        ),
        "variant": (
            result.variant.name
        ),
        "aggregationMethod": (
            BENCHMARK_AGGREGATION_METHOD
        ),
        "measuredRunCount": len(
            result.measured_run_ids
        ),
    }


def materialize_benchmark_result(
    result: CanonicalBenchmarkResult,
    *,
    project: str | Path = ".",
) -> ArtifactRecord:
    """Materialize one immutable Benchmark Result as canonical Artifact."""

    if not isinstance(
        result,
        CanonicalBenchmarkResult,
    ):
        raise TypeError(
            "result must be a CanonicalBenchmarkResult"
        )

    project_root = Path(
        project
    ).expanduser().resolve()

    if not project_root.is_dir():
        raise NotADirectoryError(
            f"project directory does not exist: {project_root}"
        )

    payload = benchmark_result_bytes(
        result
    )

    entity = (
        benchmark_result_artifact_entity(
            result
        )
    )

    # Stage inside the project solely so materialized_storage receives a normal
    # project-relative source path.  The staging directory is removed after
    # canonical immutable materialization completes.
    with tempfile.TemporaryDirectory(
        prefix=".nodrix-benchmark-result-",
        dir=project_root,
    ) as temporary:
        source = (
            Path(temporary)
            / "benchmark-result.json"
        )

        source.write_bytes(
            payload
        )

        relative_source = (
            source.relative_to(
                project_root
            )
        )

        artifact = materialize_artifact(
            project=project_root,
            source=relative_source,
            entity=entity,
            kind=(
                BENCHMARK_RESULT_ARTIFACT_KIND
            ),
            media_type=(
                BENCHMARK_RESULT_MEDIA_TYPE
            ),
            metadata=(
                benchmark_result_artifact_metadata(
                    result
                )
            ),
        )

    return artifact


def benchmark_result_artifact_payload_path(
    project: str | Path,
    artifact: ArtifactRecord,
) -> Path:
    """Return canonical local payload path for one materialized result."""

    if not isinstance(
        artifact,
        ArtifactRecord,
    ):
        raise TypeError(
            "artifact must be an ArtifactRecord"
        )

    if (
        artifact.kind
        != BENCHMARK_RESULT_ARTIFACT_KIND
    ):
        raise ValueError(
            "artifact is not a Benchmark Result Artifact"
        )

    return (
        artifact_revision_directory(
            project,
            artifact.revision,
        )
        / "payload"
    )


def read_benchmark_result_artifact(
    project: str | Path,
    artifact: ArtifactRecord,
) -> Mapping[str, Any]:
    """Read and validate one materialized Benchmark Result payload."""

    path = (
        benchmark_result_artifact_payload_path(
            project,
            artifact,
        )
    )

    try:
        document = json.loads(
            path.read_text(
                encoding="utf-8"
            ),
            parse_constant=(
                _reject_json_constant
            ),
        )
    except FileNotFoundError:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "invalid materialized Benchmark Result payload"
        ) from exc

    if not isinstance(
        document,
        Mapping,
    ):
        raise TypeError(
            "materialized Benchmark Result must be a JSON object"
        )

    return (
        validate_benchmark_result_document(
            document
        )
    )


__all__ = [
    "BENCHMARK_RESULT_ARTIFACT_ENTITY_SCHEMA",
    "BENCHMARK_RESULT_ARTIFACT_KIND",
    "BENCHMARK_RESULT_MEDIA_TYPE",
    "benchmark_result_artifact_entity",
    "benchmark_result_artifact_metadata",
    "benchmark_result_artifact_payload_path",
    "benchmark_result_bytes",
    "materialize_benchmark_result",
    "read_benchmark_result_artifact",
]
