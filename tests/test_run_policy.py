from __future__ import annotations

import json

import pytest

from nodrix.execution_policy import (
    ExecutionPolicy,
)
from nodrix.redaction import (
    RedactionPolicy,
)
from nodrix.run_environment import (
    RunEnvironmentPolicy,
)
from nodrix.run_logs import (
    RunLogPolicy,
)
from nodrix.run_policy import (
    RUN_POLICY_API_VERSION,
    RUN_POLICY_KIND,
    RunPolicyCorruptionError,
    RunPolicyStore,
)
from nodrix.run_session import (
    RunStore,
)
from nodrix.system.canonical import (
    plan_canonical_system,
)
from nodrix.system.model import (
    SystemModel,
)


def _session(
    tmp_path,
):
    plan = plan_canonical_system(
        SystemModel(
            name="policy-demo"
        )
    )

    return RunStore(
        tmp_path / "runs"
    ).create(
        plan,
        run_id="run_policy_demo",
    )


def test_policy_store_starts_without_document(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunPolicyStore(
        session,
        policy=ExecutionPolicy(),
    )

    assert store.read() is None
    assert not store.path.exists()


def test_policy_store_publishes_default_policy(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunPolicyStore(
        session,
        policy=ExecutionPolicy(),
    )

    document = store.create()

    assert store.path.is_file()

    assert (
        document["apiVersion"]
        == RUN_POLICY_API_VERSION
    )
    assert (
        document["kind"]
        == RUN_POLICY_KIND
    )
    assert (
        document["runId"]
        == session.run_id
    )
    assert (
        document["planId"]
        == session.plan_id
    )

    assert (
        document["environment"][
            "variables"
        ]
        == []
    )

    assert (
        document["logs"][
            "enabled"
        ]
        is False
    )

    assert (
        store.read()
        == document
    )


def test_policy_store_preserves_non_secret_configuration(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    policy = ExecutionPolicy(
        environment=(
            RunEnvironmentPolicy(
                variables=(
                    "ROS_DOMAIN_ID",
                    "RMW_IMPLEMENTATION",
                ),
            )
        ),
        logs=RunLogPolicy(
            enabled=True,
            min_level="info",
            categories=(
                "mapping",
                "sdk",
            ),
            max_bytes=2048,
            max_category_bytes=1024,
            max_record_bytes=512,
            overflow="stop_capture",
        ),
    )

    document = RunPolicyStore(
        session,
        policy=policy,
    ).create()

    assert document[
        "environment"
    ]["variables"] == [
        "RMW_IMPLEMENTATION",
        "ROS_DOMAIN_ID",
    ]

    logs = document[
        "logs"
    ]

    assert logs[
        "enabled"
    ] is True
    assert logs[
        "minLevel"
    ] == "info"
    assert logs[
        "categories"
    ] == [
        "mapping",
        "sdk",
    ]
    assert logs[
        "maxBytes"
    ] == 2048
    assert logs[
        "maxCategoryBytes"
    ] == 1024
    assert logs[
        "maxRecordBytes"
    ] == 512
    assert logs[
        "overflow"
    ] == "stop_capture"


def test_policy_store_never_persists_literal_redaction_secrets(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    first_secret = (
        "super-secret-value"
    )
    second_secret = (
        "another-private-value"
    )

    redaction = RedactionPolicy(
        secrets=(
            first_secret,
            second_secret,
        ),
    )

    policy = ExecutionPolicy(
        environment=(
            RunEnvironmentPolicy(
                redaction=redaction,
            )
        ),
        logs=RunLogPolicy(
            redaction=redaction,
        ),
    )

    store = RunPolicyStore(
        session,
        policy=policy,
    )

    document = store.create()

    raw = store.path.read_text(
        encoding="utf-8"
    )

    assert first_secret not in raw
    assert second_secret not in raw

    for section in (
        "environment",
        "logs",
    ):
        secret_values = (
            document[
                section
            ][
                "redaction"
            ][
                "secretValues"
            ]
        )

        assert secret_values == {
            "configured": True,
            "count": 2,
            "persisted": False,
        }


def test_policy_store_never_overwrites_existing_history(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunPolicyStore(
        session,
        policy=ExecutionPolicy(),
    )

    first = store.create()

    with pytest.raises(
        FileExistsError,
    ):
        store.create()

    assert (
        store.read()
        == first
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        (
            "runId",
            "run_other",
            "runId does not match",
        ),
        (
            "planId",
            "plan-other",
            "planId does not match",
        ),
    ),
)
def test_policy_reader_rejects_identity_mismatch(
    tmp_path,
    field,
    value,
    message,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunPolicyStore(
        session,
        policy=ExecutionPolicy(),
    )

    document = store.create()

    document[
        field
    ] = value

    store.path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunPolicyCorruptionError,
        match=message,
    ):
        store.read()


@pytest.mark.parametrize(
    "constant",
    (
        "NaN",
        "Infinity",
        "-Infinity",
    ),
)
def test_policy_reader_rejects_nonstandard_json_constants(
    tmp_path,
    constant,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunPolicyStore(
        session,
        policy=ExecutionPolicy(),
    )

    store.create()

    raw = store.path.read_text(
        encoding="utf-8"
    )

    raw = raw.replace(
        '"maxBytes": 4194304',
        f'"maxBytes": {constant}',
        1,
    )

    store.path.write_text(
        raw,
        encoding="utf-8",
    )

    with pytest.raises(
        RunPolicyCorruptionError,
        match="invalid JSON",
    ):
        store.read()


def test_policy_reader_rejects_claim_that_secrets_were_persisted(
    tmp_path,
) -> None:
    session = _session(
        tmp_path
    )

    store = RunPolicyStore(
        session,
        policy=ExecutionPolicy(),
    )

    document = store.create()

    secret_values = (
        document[
            "logs"
        ][
            "redaction"
        ][
            "secretValues"
        ]
    )

    secret_values[
        "persisted"
    ] = True

    store.path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RunPolicyCorruptionError,
        match="persisted must be false",
    ):
        store.read()
