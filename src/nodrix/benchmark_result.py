"""Versioned immutable result contract for canonical Nodrix benchmarks.

A Benchmark Result is derived evidence over ordinary canonical Runs.  It is
not another Run type and does not own execution lifecycle.

This module is deliberately storage-neutral.  Materialization as an Artifact
belongs to the canonical Artifact/storage layer and is added separately.

Result identity is content-addressed and excludes storage location and
timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from .benchmark_runs import (
    CanonicalBenchmarkAggregation,
)
from .benchmarking import (
    BenchmarkVariant,
)


BENCHMARK_RESULT_API_VERSION = (
    "nodrix.benchmark-result/v1"
)

BENCHMARK_RESULT_KIND = (
    "BenchmarkResult"
)

BENCHMARK_RESULT_IDENTITY_ALGORITHM = (
    "sha256"
)

BENCHMARK_AGGREGATION_METHOD = (
    "canonical-run-weighted/v1"
)


def _required_text(
    value: object,
    *,
    field_name: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            f"{field_name} must be a string"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} must be non-empty"
        )

    return normalized


def _canonical_json_bytes(
    document: Mapping[str, Any],
) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        allow_nan=False,
    ).encode(
        "utf-8"
    )


@dataclass(
    frozen=True,
    slots=True,
)
class BenchmarkResultVariant:
    """Exact benchmark variant semantics represented by one result."""

    name: str
    profile: str | None = None
    set_values: tuple[
        str,
        ...,
    ] = ()
    block_values: tuple[
        str,
        ...,
    ] = ()

    def __post_init__(
        self,
    ) -> None:
        object.__setattr__(
            self,
            "name",
            _required_text(
                self.name,
                field_name="variant name",
            ),
        )

        if self.profile is not None:
            object.__setattr__(
                self,
                "profile",
                _required_text(
                    self.profile,
                    field_name="variant profile",
                ),
            )

        for field_name in (
            "set_values",
            "block_values",
        ):
            values = getattr(
                self,
                field_name,
            )

            if not isinstance(
                values,
                tuple,
            ):
                raise TypeError(
                    f"{field_name} must be a tuple"
                )

            normalized = tuple(
                _required_text(
                    value,
                    field_name=field_name,
                )
                for value
                in values
            )

            object.__setattr__(
                self,
                field_name,
                normalized,
            )

    @classmethod
    def from_variant(
        cls,
        variant: BenchmarkVariant,
    ) -> "BenchmarkResultVariant":
        if not isinstance(
            variant,
            BenchmarkVariant,
        ):
            raise TypeError(
                "variant must be a BenchmarkVariant"
            )

        return cls(
            name=variant.name,
            profile=variant.profile,
            set_values=tuple(
                variant.set_values
            ),
            block_values=tuple(
                variant.block_values
            ),
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "name": self.name,
            "profile": self.profile,
            "set": list(
                self.set_values
            ),
            "block": list(
                self.block_values
            ),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class BenchmarkResultIdentity:
    """Content-addressed identity of one immutable Benchmark Result."""

    algorithm: str
    digest: str

    def __post_init__(
        self,
    ) -> None:
        algorithm = _required_text(
            self.algorithm,
            field_name="identity algorithm",
        )

        if (
            algorithm
            != BENCHMARK_RESULT_IDENTITY_ALGORITHM
        ):
            raise ValueError(
                "unsupported Benchmark Result "
                "identity algorithm"
            )

        digest = _required_text(
            self.digest,
            field_name="identity digest",
        )

        if (
            len(digest) != 64
            or any(
                character
                not in "0123456789abcdef"
                for character
                in digest
            )
        ):
            raise ValueError(
                "Benchmark Result digest must be "
                "a lowercase SHA-256 hex digest"
            )

        object.__setattr__(
            self,
            "algorithm",
            algorithm,
        )

        object.__setattr__(
            self,
            "digest",
            digest,
        )

    @property
    def value(
        self,
    ) -> str:
        return (
            f"{self.algorithm}:"
            f"{self.digest}"
        )

    def to_dict(
        self,
    ) -> dict[str, str]:
        return {
            "algorithm": (
                self.algorithm
            ),
            "digest": (
                self.digest
            ),
        }


def _semantic_document(
    *,
    benchmark_plan_id: str,
    variant: BenchmarkResultVariant,
    aggregation: CanonicalBenchmarkAggregation,
) -> dict[str, object]:
    return {
        "apiVersion": (
            BENCHMARK_RESULT_API_VERSION
        ),
        "kind": (
            BENCHMARK_RESULT_KIND
        ),
        "benchmarkPlanId": (
            benchmark_plan_id
        ),
        "variant": (
            variant.to_dict()
        ),
        "aggregationMethod": (
            BENCHMARK_AGGREGATION_METHOD
        ),
        "result": (
            aggregation.to_dict()
        ),
    }


def canonical_benchmark_result_identity(
    *,
    benchmark_plan_id: str,
    variant: BenchmarkResultVariant,
    aggregation: CanonicalBenchmarkAggregation,
) -> BenchmarkResultIdentity:
    """Return deterministic content identity for one Benchmark Result."""

    benchmark_plan_id = _required_text(
        benchmark_plan_id,
        field_name="benchmark_plan_id",
    )

    if not isinstance(
        variant,
        BenchmarkResultVariant,
    ):
        raise TypeError(
            "variant must be BenchmarkResultVariant"
        )

    if not isinstance(
        aggregation,
        CanonicalBenchmarkAggregation,
    ):
        raise TypeError(
            "aggregation must be CanonicalBenchmarkAggregation"
        )

    document = _semantic_document(
        benchmark_plan_id=(
            benchmark_plan_id
        ),
        variant=variant,
        aggregation=aggregation,
    )

    digest = hashlib.sha256(
        _canonical_json_bytes(
            document
        )
    ).hexdigest()

    return BenchmarkResultIdentity(
        algorithm=(
            BENCHMARK_RESULT_IDENTITY_ALGORITHM
        ),
        digest=digest,
    )


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalBenchmarkResult:
    """Immutable versioned aggregate result for one Benchmark variant."""

    benchmark_plan_id: str
    variant: BenchmarkResultVariant
    aggregation: CanonicalBenchmarkAggregation
    identity: BenchmarkResultIdentity

    def __post_init__(
        self,
    ) -> None:
        benchmark_plan_id = _required_text(
            self.benchmark_plan_id,
            field_name="benchmark_plan_id",
        )

        if not isinstance(
            self.variant,
            BenchmarkResultVariant,
        ):
            raise TypeError(
                "variant must be BenchmarkResultVariant"
            )

        if not isinstance(
            self.aggregation,
            CanonicalBenchmarkAggregation,
        ):
            raise TypeError(
                "aggregation must be CanonicalBenchmarkAggregation"
            )

        if not isinstance(
            self.identity,
            BenchmarkResultIdentity,
        ):
            raise TypeError(
                "identity must be BenchmarkResultIdentity"
            )

        expected = (
            canonical_benchmark_result_identity(
                benchmark_plan_id=(
                    benchmark_plan_id
                ),
                variant=self.variant,
                aggregation=self.aggregation,
            )
        )

        if self.identity != expected:
            raise ValueError(
                "Benchmark Result identity does not "
                "match result semantics"
            )

        object.__setattr__(
            self,
            "benchmark_plan_id",
            benchmark_plan_id,
        )

    @property
    def measured_run_ids(
        self,
    ) -> tuple[str, ...]:
        return (
            self.aggregation
            .aggregate
            .run_ids
        )

    def to_dict(
        self,
    ) -> dict[str, object]:
        semantic = _semantic_document(
            benchmark_plan_id=(
                self.benchmark_plan_id
            ),
            variant=self.variant,
            aggregation=self.aggregation,
        )

        return {
            "apiVersion": (
                semantic[
                    "apiVersion"
                ]
            ),
            "kind": (
                semantic[
                    "kind"
                ]
            ),
            "identity": (
                self.identity.to_dict()
            ),
            "benchmarkPlanId": (
                semantic[
                    "benchmarkPlanId"
                ]
            ),
            "variant": (
                semantic[
                    "variant"
                ]
            ),
            "aggregationMethod": (
                semantic[
                    "aggregationMethod"
                ]
            ),
            "measuredRuns": list(
                self.measured_run_ids
            ),
            "result": (
                semantic[
                    "result"
                ]
            ),
        }


def create_canonical_benchmark_result(
    *,
    benchmark_plan_id: str,
    variant: BenchmarkVariant | BenchmarkResultVariant,
    aggregation: CanonicalBenchmarkAggregation,
) -> CanonicalBenchmarkResult:
    """Create one deterministic Benchmark Result from canonical Run evidence."""

    if isinstance(
        variant,
        BenchmarkVariant,
    ):
        canonical_variant = (
            BenchmarkResultVariant.from_variant(
                variant
            )
        )
    elif isinstance(
        variant,
        BenchmarkResultVariant,
    ):
        canonical_variant = variant
    else:
        raise TypeError(
            "variant must be BenchmarkVariant "
            "or BenchmarkResultVariant"
        )

    benchmark_plan_id = _required_text(
        benchmark_plan_id,
        field_name="benchmark_plan_id",
    )

    identity = (
        canonical_benchmark_result_identity(
            benchmark_plan_id=(
                benchmark_plan_id
            ),
            variant=(
                canonical_variant
            ),
            aggregation=aggregation,
        )
    )

    return CanonicalBenchmarkResult(
        benchmark_plan_id=(
            benchmark_plan_id
        ),
        variant=canonical_variant,
        aggregation=aggregation,
        identity=identity,
    )


def validate_benchmark_result_document(
    document: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Validate the stable top-level Benchmark Result wire contract.

    Deep aggregate semantics are produced by typed canonical objects.  This
    boundary verifies version/kind, exact top-level shape and content identity.
    """

    if not isinstance(
        document,
        Mapping,
    ):
        raise TypeError(
            "Benchmark Result document must be a mapping"
        )

    value = dict(
        document
    )

    expected_fields = {
        "apiVersion",
        "kind",
        "identity",
        "benchmarkPlanId",
        "variant",
        "aggregationMethod",
        "measuredRuns",
        "result",
    }

    actual_fields = set(
        value
    )

    if (
        actual_fields
        != expected_fields
    ):
        raise ValueError(
            "Benchmark Result document has invalid fields; "
            f"missing={sorted(expected_fields - actual_fields)}, "
            f"extra={sorted(actual_fields - expected_fields)}"
        )

    if (
        value[
            "apiVersion"
        ]
        != BENCHMARK_RESULT_API_VERSION
    ):
        raise ValueError(
            "unsupported Benchmark Result apiVersion"
        )

    if (
        value[
            "kind"
        ]
        != BENCHMARK_RESULT_KIND
    ):
        raise ValueError(
            "invalid Benchmark Result kind"
        )

    if (
        value[
            "aggregationMethod"
        ]
        != BENCHMARK_AGGREGATION_METHOD
    ):
        raise ValueError(
            "unsupported Benchmark aggregation method"
        )

    benchmark_plan_id = _required_text(
        value[
            "benchmarkPlanId"
        ],
        field_name="benchmarkPlanId",
    )

    raw_variant = value[
        "variant"
    ]

    if not isinstance(
        raw_variant,
        Mapping,
    ):
        raise TypeError(
            "variant must be a mapping"
        )

    variant_document = dict(
        raw_variant
    )

    if set(
        variant_document
    ) != {
        "name",
        "profile",
        "set",
        "block",
    }:
        raise ValueError(
            "variant has invalid fields"
        )

    raw_set = variant_document[
        "set"
    ]

    raw_block = variant_document[
        "block"
    ]

    if not isinstance(
        raw_set,
        list,
    ):
        raise TypeError(
            "variant.set must be a list"
        )

    if not isinstance(
        raw_block,
        list,
    ):
        raise TypeError(
            "variant.block must be a list"
        )

    variant = BenchmarkResultVariant(
        name=variant_document[
            "name"
        ],
        profile=variant_document[
            "profile"
        ],
        set_values=tuple(
            raw_set
        ),
        block_values=tuple(
            raw_block
        ),
    )

    raw_identity = value[
        "identity"
    ]

    if not isinstance(
        raw_identity,
        Mapping,
    ):
        raise TypeError(
            "identity must be a mapping"
        )

    identity_document = dict(
        raw_identity
    )

    if set(
        identity_document
    ) != {
        "algorithm",
        "digest",
    }:
        raise ValueError(
            "identity has invalid fields"
        )

    identity = BenchmarkResultIdentity(
        algorithm=(
            identity_document[
                "algorithm"
            ]
        ),
        digest=(
            identity_document[
                "digest"
            ]
        ),
    )

    raw_result = value[
        "result"
    ]

    if not isinstance(
        raw_result,
        Mapping,
    ):
        raise TypeError(
            "result must be a mapping"
        )

    measured_runs = value[
        "measuredRuns"
    ]

    if not isinstance(
        measured_runs,
        list,
    ):
        raise TypeError(
            "measuredRuns must be a list"
        )

    for run_id in measured_runs:
        _required_text(
            run_id,
            field_name="measured Run id",
        )

    # Validate identity directly from the wire semantic projection.  This
    # avoids reconstructing every nested aggregate type at this storage-neutral
    # boundary while still detecting any semantic mutation.
    semantic_document = {
        "apiVersion": (
            BENCHMARK_RESULT_API_VERSION
        ),
        "kind": (
            BENCHMARK_RESULT_KIND
        ),
        "benchmarkPlanId": (
            benchmark_plan_id
        ),
        "variant": (
            variant.to_dict()
        ),
        "aggregationMethod": (
            BENCHMARK_AGGREGATION_METHOD
        ),
        "result": dict(
            raw_result
        ),
    }

    expected_digest = hashlib.sha256(
        _canonical_json_bytes(
            semantic_document
        )
    ).hexdigest()

    if (
        identity.digest
        != expected_digest
    ):
        raise ValueError(
            "Benchmark Result identity does not "
            "match document semantics"
        )

    aggregate = raw_result.get(
        "aggregate"
    )

    if not isinstance(
        aggregate,
        Mapping,
    ):
        raise TypeError(
            "result.aggregate must be a mapping"
        )

    aggregate_runs = (
        aggregate.get(
            "runs"
        )
    )

    if not isinstance(
        aggregate_runs,
        list,
    ):
        raise TypeError(
            "result.aggregate.runs must be a list"
        )

    if measured_runs != aggregate_runs:
        raise ValueError(
            "measuredRuns must match "
            "result.aggregate.runs"
        )

    return value


__all__ = [
    "BENCHMARK_AGGREGATION_METHOD",
    "BENCHMARK_RESULT_API_VERSION",
    "BENCHMARK_RESULT_IDENTITY_ALGORITHM",
    "BENCHMARK_RESULT_KIND",
    "BenchmarkResultIdentity",
    "BenchmarkResultVariant",
    "CanonicalBenchmarkResult",
    "canonical_benchmark_result_identity",
    "create_canonical_benchmark_result",
    "validate_benchmark_result_document",
]
