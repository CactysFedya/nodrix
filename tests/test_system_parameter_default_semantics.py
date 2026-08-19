from __future__ import annotations

import pytest

from nodrix.system.canonical import system_plan_digest
from nodrix.system.contracts import (
    SystemBoundaryBindings,
    SystemParameter,
    SystemParameterBinding,
)
from nodrix.system.definition import system_definition_digest
from nodrix.system.instances import ApplicationInstance
from nodrix.system.io import loads_system, system_to_canonical
from nodrix.system.model import SystemModel
from nodrix.system.planning import plan_system


def _parameter_system(
    parameter: SystemParameter,
) -> SystemModel:
    return SystemModel(
        name="default-semantics",
        parameters=(parameter,),
    )


def _bound_parameter_system(
    parameter: SystemParameter,
) -> SystemModel:
    return SystemModel(
        name="default-binding",
        parameters=(parameter,),
        applications=(
            ApplicationInstance(
                name="worker",
                uses="demo.worker",
            ),
        ),
        bindings=SystemBoundaryBindings(
            parameters=(
                SystemParameterBinding(
                    parameter="value",
                    targets=(
                        "application:worker.value",
                    ),
                ),
            ),
        ),
    )


def test_parameter_distinguishes_missing_and_explicit_null_default() -> None:
    missing = SystemParameter(
        name="value",
        type="string",
        nullable=True,
    )
    explicit_null = SystemParameter(
        name="value",
        type="string",
        nullable=True,
        default=None,
    )

    assert missing.default is None
    assert explicit_null.default is None

    assert missing.has_default is False
    assert explicit_null.has_default is True

    # Pydantic copies must preserve authoring presence semantics.
    assert missing.model_copy().has_default is False
    assert explicit_null.model_copy().has_default is True


def test_explicit_null_default_requires_nullable_parameter() -> None:
    with pytest.raises(
        ValueError,
        match="default does not match parameter type",
    ):
        SystemParameter(
            name="value",
            type="string",
            default=None,
        )

    parameter = SystemParameter(
        name="value",
        type="string",
        nullable=True,
        default=None,
    )

    assert parameter.has_default is True
    assert parameter.default is None


def test_canonical_definition_preserves_explicit_null_default() -> None:
    missing = _parameter_system(
        SystemParameter(
            name="value",
            type="string",
            nullable=True,
        )
    )
    explicit_null = _parameter_system(
        SystemParameter(
            name="value",
            type="string",
            nullable=True,
            default=None,
        )
    )

    missing_document = system_to_canonical(
        missing
    )
    explicit_document = system_to_canonical(
        explicit_null
    )

    assert (
        "default"
        not in missing_document["parameters"][0]
    )
    assert (
        explicit_document["parameters"][0]["default"]
        is None
    )

    # The two Definitions differ semantically and therefore must have
    # different immutable revisions.
    assert (
        system_definition_digest(missing)
        != system_definition_digest(explicit_null)
    )

    loaded = loads_system(
        """
apiVersion: nodrix.system/v1
kind: System
name: explicit-null
parameters:
  - name: value
    type: string
    nullable: true
    default: null
""",
        format="yaml",
    )

    loaded_parameter = loaded.parameter(
        "value"
    )

    assert loaded_parameter.has_default is True
    assert loaded_parameter.default is None
    assert (
        system_to_canonical(loaded)["parameters"][0]["default"]
        is None
    )


def test_planner_propagates_explicit_null_but_not_missing_default() -> None:
    missing = _bound_parameter_system(
        SystemParameter(
            name="value",
            type="string",
            nullable=True,
        )
    )
    explicit_null = _bound_parameter_system(
        SystemParameter(
            name="value",
            type="string",
            nullable=True,
            default=None,
        )
    )

    missing_plan = plan_system(
        missing
    )
    explicit_plan = plan_system(
        explicit_null
    )

    missing_parameter = (
        missing_plan.parameters[0]
    )
    explicit_parameter = (
        explicit_plan.parameters[0]
    )

    assert missing_parameter.has_default is False
    assert missing_parameter.default is None
    assert missing_parameter.value is None
    assert missing_parameter.configured is False

    assert explicit_parameter.has_default is True
    assert explicit_parameter.default is None
    assert explicit_parameter.value is None
    assert explicit_parameter.configured is False

    # A missing default does not configure the internal target.
    assert (
        missing_plan.applications[0].parameters
        == {}
    )

    # An explicit null default is an effective value and must cross
    # the public parameter binding.
    assert (
        explicit_plan.applications[0].parameters
        == {"value": None}
    )

    missing_payload = missing_plan.model_dump(
        mode="json"
    )
    explicit_payload = explicit_plan.model_dump(
        mode="json"
    )

    assert (
        missing_payload["parameters"][0]["has_default"]
        is False
    )
    assert (
        explicit_payload["parameters"][0]["has_default"]
        is True
    )

    # Exact Plans must no longer collapse these two contracts.
    assert (
        system_plan_digest(missing_plan)
        != system_plan_digest(explicit_plan)
    )
