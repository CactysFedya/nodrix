from __future__ import annotations

from nodrix.model import (
    DERIVED_FROM as ModelDerivedFrom,
)
from nodrix.model import (
    SUPERSEDES as ModelSupersedes,
)
from nodrix.model import (
    ArtifactRecord as ModelArtifactRecord,
)
from nodrix.model import (
    DatasetRecord as ModelDatasetRecord,
)
from nodrix.model import (
    MaterializedRef as ModelMaterializedRef,
)
from nodrix.model import (
    Relation as ModelRelation,
)
from nodrix.model import (
    RelationGraph as ModelRelationGraph,
)
from nodrix.model import (
    RelationKind as ModelRelationKind,
)
from nodrix.model import (
    combine_provenance as model_combine_provenance,
)
from nodrix.model import (
    materialized_lineage_relations
    as model_materialized_lineage_relations,
)
from nodrix.model import (
    materialized_revision
    as model_materialized_revision,
)
from nodrix.model import (
    superseded_by as model_superseded_by,
)
from nodrix.sdk import (
    DERIVED_FROM,
    SUPERSEDES,
    ArtifactRecord,
    DatasetRecord,
    MaterializedRef,
    Relation,
    RelationGraph,
    RelationKind,
    combine_provenance,
    materialized_lineage_relations,
    materialized_revision,
    superseded_by,
)


def test_sdk_reexports_materialized_records_exactly() -> None:
    assert (
        DatasetRecord
        is ModelDatasetRecord
    )

    assert (
        ArtifactRecord
        is ModelArtifactRecord
    )


def test_sdk_reexports_materialized_reference_exactly() -> None:
    assert (
        MaterializedRef
        is ModelMaterializedRef
    )


def test_sdk_reexports_relation_model_exactly() -> None:
    assert (
        Relation
        is ModelRelation
    )

    assert (
        RelationGraph
        is ModelRelationGraph
    )

    assert (
        RelationKind
        is ModelRelationKind
    )


def test_sdk_reexports_lineage_kinds_exactly() -> None:
    assert (
        DERIVED_FROM
        is ModelDerivedFrom
    )

    assert (
        SUPERSEDES
        is ModelSupersedes
    )


def test_sdk_reexports_lineage_helpers_exactly() -> None:
    assert (
        materialized_revision
        is model_materialized_revision
    )

    assert (
        materialized_lineage_relations
        is model_materialized_lineage_relations
    )

    assert (
        superseded_by
        is model_superseded_by
    )

    assert (
        combine_provenance
        is model_combine_provenance
    )


def test_sdk_does_not_define_parallel_dataset_artifact_types() -> None:
    assert (
        DatasetRecord.__module__
        == "nodrix.model.data"
    )

    assert (
        ArtifactRecord.__module__
        == "nodrix.model.data"
    )


def test_sdk_relation_types_remain_canonical_model_types() -> None:
    assert (
        Relation.__module__
        == "nodrix.model.relations"
    )

    assert (
        RelationGraph.__module__
        == "nodrix.model.relations"
    )

    assert (
        RelationKind.__module__
        == "nodrix.model.relations"
    )


def test_sdk_does_not_expose_run_persistence_api() -> None:
    import nodrix.sdk as sdk

    assert not hasattr(
        sdk,
        "persist_execution",
    )

    assert not hasattr(
        sdk,
        "PersistedRun",
    )

    assert not hasattr(
        sdk,
        "write_run_document",
    )


def test_sdk_does_not_expose_run_provenance_construction() -> None:
    import nodrix.sdk as sdk

    assert not hasattr(
        sdk,
        "run_io_relations",
    )

    assert not hasattr(
        sdk,
        "run_ref",
    )
