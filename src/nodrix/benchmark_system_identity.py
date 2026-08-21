"""Canonical identity for Benchmark workload sets over resolved Systems.

The historical BenchmarkPlan still carries Pipeline-era authoring fields.
Canonical System benchmarking must not derive identity from those raw fields.

Instead, one Benchmark workload-set revision is defined by exact resolved
System revisions and exact canonical System Plan IDs for every named variant.

Execution controls such as repeat/warmup belong to the Benchmark Plan, not to
the workload-set revision.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from .benchmarking import (
    BenchmarkPlan,
)
from .model import (
    BENCHMARK,
    BENCHMARK_PLAN,
    SYSTEM_EXECUTION,
    EntityRef,
    Operation,
    PlanRecord,
    RevisionRef,
    canonical_plan_id,
)


BENCHMARK_WORKLOAD_SET_API_VERSION = (
    "nodrix.benchmark-workload-set/v1"
)

BENCHMARK_WORKLOAD_SET_KIND = (
    "BenchmarkWorkloadSet"
)


def _required_text(
    value: str,
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


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalBenchmarkWorkloadVariant:
    """Identity of one exact resolved workload variant."""

    name: str
    system_revision: RevisionRef
    system_plan_id: str

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

        if not isinstance(
            self.system_revision,
            RevisionRef,
        ):
            raise TypeError(
                "system_revision must be "
                "a RevisionRef"
            )

        if (
            self.system_revision
            .entity
            .kind
            != "system"
        ):
            raise ValueError(
                "system_revision must identify "
                "a System entity"
            )

        object.__setattr__(
            self,
            "system_plan_id",
            _required_text(
                self.system_plan_id,
                field_name=(
                    "system_plan_id"
                ),
            ),
        )

    def to_dict(
        self,
    ) -> dict[str, str]:
        return {
            "name": self.name,
            "systemRevision": (
                self
                .system_revision
                .canonical
            ),
            "systemPlanId": (
                self.system_plan_id
            ),
        }


def _workload_semantic_document(
    *,
    system: EntityRef,
    variants: tuple[
        CanonicalBenchmarkWorkloadVariant,
        ...,
    ],
) -> dict[str, object]:
    return {
        "apiVersion": (
            BENCHMARK_WORKLOAD_SET_API_VERSION
        ),
        "kind": (
            BENCHMARK_WORKLOAD_SET_KIND
        ),
        "system": system.canonical,
        "variants": [
            variant.to_dict()
            for variant
            in variants
        ],
    }


def benchmark_workload_set_digest(
    *,
    system: EntityRef,
    variants: tuple[
        CanonicalBenchmarkWorkloadVariant,
        ...,
    ],
) -> str:
    """Return deterministic semantic digest of one resolved workload set."""

    if not isinstance(
        system,
        EntityRef,
    ):
        raise TypeError(
            "system must be an EntityRef"
        )

    if system.kind != "system":
        raise ValueError(
            "workload-set system must have "
            "kind 'system'"
        )

    if not isinstance(
        variants,
        tuple,
    ):
        raise TypeError(
            "variants must be a tuple"
        )

    if not variants:
        raise ValueError(
            "workload set requires at least "
            "one variant"
        )

    if not all(
        isinstance(
            variant,
            CanonicalBenchmarkWorkloadVariant,
        )
        for variant
        in variants
    ):
        raise TypeError(
            "variants must contain "
            "CanonicalBenchmarkWorkloadVariant values"
        )

    document = (
        _workload_semantic_document(
            system=system,
            variants=variants,
        )
    )

    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        encoded
    ).hexdigest()


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalBenchmarkWorkloadSet:
    """Immutable logical Benchmark Definition and exact semantic revision."""

    entity: EntityRef
    revision: RevisionRef
    system: EntityRef
    variants: tuple[
        CanonicalBenchmarkWorkloadVariant,
        ...,
    ]

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.entity,
            EntityRef,
        ):
            raise TypeError(
                "entity must be an EntityRef"
            )

        if self.entity.kind != "benchmark":
            raise ValueError(
                "Benchmark workload-set entity "
                "must have kind 'benchmark'"
            )

        if not isinstance(
            self.revision,
            RevisionRef,
        ):
            raise TypeError(
                "revision must be a RevisionRef"
            )

        if (
            self.revision.entity
            != self.entity
        ):
            raise ValueError(
                "Benchmark workload-set revision "
                "must belong to its entity"
            )

        if not isinstance(
            self.system,
            EntityRef,
        ):
            raise TypeError(
                "system must be an EntityRef"
            )

        if self.system.kind != "system":
            raise ValueError(
                "workload-set system must have "
                "kind 'system'"
            )

        if not isinstance(
            self.variants,
            tuple,
        ):
            raise TypeError(
                "variants must be a tuple"
            )

        if not self.variants:
            raise ValueError(
                "workload set requires at least "
                "one variant"
            )

        names = tuple(
            variant.name
            for variant
            in self.variants
        )

        if len(
            names
        ) != len(
            set(
                names
            )
        ):
            raise ValueError(
                "workload-set variant names "
                "must be unique"
            )

        for variant in self.variants:
            if (
                variant
                .system_revision
                .entity
                != self.system
            ):
                raise ValueError(
                    "all Benchmark variants must "
                    "target the same logical System"
                )

        expected_digest = (
            benchmark_workload_set_digest(
                system=self.system,
                variants=self.variants,
            )
        )

        if (
            self.revision.algorithm
            != "sha256"
            or self.revision.digest
            != expected_digest
        ):
            raise ValueError(
                "Benchmark workload-set revision "
                "does not match workload semantics"
            )

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            **_workload_semantic_document(
                system=self.system,
                variants=self.variants,
            ),
            "entity": (
                self.entity.canonical
            ),
            "revision": (
                self.revision.canonical
            ),
        }


def _variant_from_plan(
    name: str,
    plan: PlanRecord,
) -> CanonicalBenchmarkWorkloadVariant:
    if not isinstance(
        plan,
        PlanRecord,
    ):
        raise TypeError(
            "variant plan must be "
            "a PlanRecord"
        )

    if (
        plan.kind
        != SYSTEM_EXECUTION
    ):
        raise ValueError(
            "Benchmark workload variant "
            "requires a System execution PlanRecord"
        )

    subject = (
        plan.operation.subject
    )

    if subject.kind != "system":
        raise ValueError(
            "Benchmark workload variant "
            "Plan subject must be a System"
        )

    revision = (
        plan.subject_revision
    )

    if not isinstance(
        revision,
        RevisionRef,
    ):
        raise ValueError(
            "System execution Plan must pin "
            "an exact subject revision"
        )

    if revision.entity != subject:
        raise ValueError(
            "System execution Plan subject "
            "and revision do not match"
        )

    return CanonicalBenchmarkWorkloadVariant(
        name=name,
        system_revision=revision,
        system_plan_id=plan.plan_id,
    )


def canonical_benchmark_workload_set(
    plan: BenchmarkPlan,
    *,
    variant_plans: Mapping[
        str,
        PlanRecord,
    ],
    name: str | None = None,
) -> CanonicalBenchmarkWorkloadSet:
    """Build exact workload-set identity from resolved canonical System Plans.

    Raw Project Profile names are intentionally not identity. Their resolved
    effects are already frozen into each exact System revision / Plan ID.

    Pipeline-era ``set`` and ``block`` mutations are rejected because they have
    no canonical System meaning.
    """

    if not isinstance(
        plan,
        BenchmarkPlan,
    ):
        raise TypeError(
            "plan must be a BenchmarkPlan"
        )

    if not isinstance(
        variant_plans,
        Mapping,
    ):
        raise TypeError(
            "variant_plans must be a mapping"
        )

    for variant in plan.variants:
        if (
            variant.set_values
            or variant.block_values
        ):
            raise ValueError(
                "canonical System Benchmark does not "
                "support legacy set/block overrides"
            )

    expected_names = tuple(
        variant.name
        for variant
        in plan.variants
    )

    actual_names = tuple(
        variant_plans.keys()
    )

    if (
        set(
            actual_names
        )
        != set(
            expected_names
        )
    ):
        raise ValueError(
            "variant_plans must match BenchmarkPlan "
            "variants exactly"
        )

    variants = tuple(
        _variant_from_plan(
            variant.name,
            variant_plans[
                variant.name
            ],
        )
        for variant
        in plan.variants
    )

    system = (
        variants[
            0
        ]
        .system_revision
        .entity
    )

    if any(
        variant
        .system_revision
        .entity
        != system
        for variant
        in variants
    ):
        raise ValueError(
            "all Benchmark variants must resolve "
            "to the same logical System entity"
        )

    entity_name = (
        _required_text(
            name,
            field_name="Benchmark name",
        )
        if name is not None
        else (
            f"{system.name}-benchmark"
        )
    )

    entity = EntityRef(
        kind="benchmark",
        namespace=system.namespace,
        name=entity_name,
    )

    digest = (
        benchmark_workload_set_digest(
            system=system,
            variants=variants,
        )
    )

    revision = RevisionRef.from_sha256(
        entity,
        digest,
    )

    return CanonicalBenchmarkWorkloadSet(
        entity=entity,
        revision=revision,
        system=system,
        variants=variants,
    )


def canonical_system_benchmark_operation(
    plan: BenchmarkPlan,
    *,
    workload_set: CanonicalBenchmarkWorkloadSet,
) -> Operation:
    """Create BENCHMARK intent over one exact canonical workload set."""

    if not isinstance(
        plan,
        BenchmarkPlan,
    ):
        raise TypeError(
            "plan must be a BenchmarkPlan"
        )

    if not isinstance(
        workload_set,
        CanonicalBenchmarkWorkloadSet,
    ):
        raise TypeError(
            "workload_set must be "
            "CanonicalBenchmarkWorkloadSet"
        )

    expected_names = tuple(
        variant.name
        for variant
        in plan.variants
    )

    workload_names = tuple(
        variant.name
        for variant
        in workload_set.variants
    )

    if workload_names != expected_names:
        raise ValueError(
            "workload-set variants must match "
            "BenchmarkPlan order exactly"
        )

    return Operation(
        kind=BENCHMARK,
        subject=workload_set.entity,
        subject_revision=(
            workload_set.revision
        ),
        parameters={
            "repeat": plan.repeat,
            "warmup": plan.warmup,
            "workloadSet": (
                workload_set
                .revision
                .canonical
            ),
            "variants": [
                variant.to_dict()
                for variant
                in workload_set.variants
            ],
        },
    )


def canonical_system_benchmark_plan_digest(
    plan: BenchmarkPlan,
    *,
    workload_set: CanonicalBenchmarkWorkloadSet,
) -> str:
    """Digest one exact Benchmark execution plan over a workload-set revision."""

    if not isinstance(
        plan,
        BenchmarkPlan,
    ):
        raise TypeError(
            "plan must be a BenchmarkPlan"
        )

    if not isinstance(
        workload_set,
        CanonicalBenchmarkWorkloadSet,
    ):
        raise TypeError(
            "workload_set must be "
            "CanonicalBenchmarkWorkloadSet"
        )

    document = {
        "workloadSet": (
            workload_set
            .revision
            .canonical
        ),
        "repeat": plan.repeat,
        "warmup": plan.warmup,
    }

    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        encoded
    ).hexdigest()


def canonical_system_benchmark_plan_record(
    plan: BenchmarkPlan,
    *,
    workload_set: CanonicalBenchmarkWorkloadSet,
    metadata: Mapping[
        str,
        Any,
    ] | None = None,
) -> PlanRecord:
    """Create canonical BENCHMARK PlanRecord without Pipeline identity."""

    operation = (
        canonical_system_benchmark_operation(
            plan,
            workload_set=workload_set,
        )
    )

    digest = (
        canonical_system_benchmark_plan_digest(
            plan,
            workload_set=workload_set,
        )
    )

    return PlanRecord(
        plan_id=canonical_plan_id(
            kind=BENCHMARK_PLAN,
            operation=operation,
            subject_revision=(
                workload_set.revision
            ),
            payload_sha256=digest,
        ),
        kind=BENCHMARK_PLAN,
        operation=operation,
        subject_revision=(
            workload_set.revision
        ),
        # Transitional authoring payload. Canonical identity above is resolved
        # workload semantics and does not depend on Pipeline-era raw fields.
        payload=plan,
        metadata={
            "benchmark_workload_set": (
                workload_set
                .revision
                .canonical
            ),
            "benchmark_workload_digest": (
                workload_set
                .revision
                .digest
            ),
            **dict(
                metadata
                or {}
            ),
        },
    )


__all__ = [
    "BENCHMARK_WORKLOAD_SET_API_VERSION",
    "BENCHMARK_WORKLOAD_SET_KIND",
    "CanonicalBenchmarkWorkloadSet",
    "CanonicalBenchmarkWorkloadVariant",
    "benchmark_workload_set_digest",
    "canonical_benchmark_workload_set",
    "canonical_system_benchmark_operation",
    "canonical_system_benchmark_plan_digest",
    "canonical_system_benchmark_plan_record",
]
