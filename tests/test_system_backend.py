from __future__ import annotations

import pytest

from nodrix.system import (
    ApplicationInstance,
    Artifact,
    BackendCapabilities,
    BackendContext,
    BackendContractError,
    BackendDiagnostic,
    BackendExecutionHandle,
    BackendExecutionState,
    BackendExecutionStatus,
    BackendValidationError,
    ExecutionBackend,
    Graph,
    NodeInstance,
    PreparedExecution,
    ResourceInstance,
    SystemLink,
    SystemModel,
    Target,
    plan_system,
)


class FakeBackend(ExecutionBackend):
    def __init__(
        self,
        backend_id: str = "local",
        *,
        capabilities: BackendCapabilities | None = None,
    ) -> None:
        super().__init__(
            backend_id,
            capabilities=capabilities
            or BackendCapabilities(
                target_kinds=frozenset({"local", "host"}),
                transport_uses=frozenset({"demo.transport"}),
                features=frozenset({"graphs", "resources"}),
            ),
        )
        self.state = BackendExecutionState.PREPARED

    def _prepare(self, context: BackendContext) -> PreparedExecution:
        self.state = BackendExecutionState.PREPARED
        return PreparedExecution(
            backend=self.backend_id,
            context=context,
            payload={"prepared": True},
        )

    def _start(
        self,
        prepared: PreparedExecution,
    ) -> BackendExecutionHandle:
        self.state = BackendExecutionState.RUNNING
        return BackendExecutionHandle(
            backend=self.backend_id,
            execution_id=f"{self.backend_id}-1",
            prepared=prepared,
            payload={"worker": "fake"},
        )

    def _inspect(
        self,
        handle: BackendExecutionHandle,
    ) -> BackendExecutionStatus:
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=self.state,
        )

    def _stop(
        self,
        handle: BackendExecutionHandle,
        *,
        timeout_seconds: float | None,
    ) -> BackendExecutionStatus:
        self.state = BackendExecutionState.STOPPED
        return BackendExecutionStatus(
            backend=self.backend_id,
            execution_id=handle.execution_id,
            state=self.state,
            details={"timeout_seconds": timeout_seconds},
        )


class RejectingBackend(FakeBackend):
    def _validate(self, context: BackendContext):
        return (
            BackendDiagnostic(
                level="error",
                code="FAKE001",
                path="nodes",
                message="fake backend rejects this plan",
            ),
        )


def _multi_backend_plan():
    system = SystemModel(
        name="robot",
        targets=(
            Target(
                name="pi",
                kind="host",
                properties={"backend": "local"},
            ),
            Target(
                name="worker",
                kind="host",
                properties={"backend": "remote"},
            ),
        ),
        resources=(
            ResourceInstance(
                name="pi_store",
                uses="storage.local",
                target="pi",
            ),
            ResourceInstance(
                name="worker_store",
                uses="storage.remote",
                target="worker",
            ),
        ),
        applications=(
            ApplicationInstance(
                name="driver",
                uses="driver.external",
                target="pi",
            ),
        ),
        graphs=(
            Graph(
                name="capture",
                nodes=(
                    NodeInstance(
                        name="source",
                        uses="demo.source",
                        target="pi",
                        resources={"storage": "pi_store"},
                    ),
                ),
            ),
            Graph(
                name="mapping",
                nodes=(
                    NodeInstance(
                        name="sink",
                        uses="demo.sink",
                        target="worker",
                        resources={"storage": "worker_store"},
                    ),
                ),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "capture/source.output",
                    "to": "mapping/sink.input",
                    "uses": "demo.transport",
                }
            ),
        ),
        artifacts=(
            Artifact(
                name="capture-log",
                kind="log",
                producer="capture/source.output",
            ),
            Artifact(
                name="map",
                kind="map",
                producer="mapping/sink.output",
            ),
        ),
    )
    return plan_system(system)


def test_backend_context_partitions_multi_backend_plan() -> None:
    plan = _multi_backend_plan()

    local = BackendContext.from_plan(plan, "local")
    remote = BackendContext.from_plan(plan, "remote")

    assert [item.name for item in local.targets] == ["pi"]
    assert [item.name for item in local.resources] == ["pi_store"]
    assert [item.name for item in local.applications] == ["driver"]
    assert [item.id for item in local.nodes] == ["capture/source"]
    assert local.graph_names == ("capture",)
    assert [item.name for item in local.artifacts] == ["capture-log"]
    assert local.resource_order == ("pi_store",)
    assert len(local.outbound_links) == 1
    assert local.inbound_links == ()

    assert [item.name for item in remote.targets] == ["worker"]
    assert [item.name for item in remote.resources] == ["worker_store"]
    assert [item.id for item in remote.nodes] == ["mapping/sink"]
    assert remote.graph_names == ("mapping",)
    assert [item.name for item in remote.artifacts] == ["map"]
    assert len(remote.inbound_links) == 1
    assert remote.outbound_links == ()


def test_context_links_preserve_plan_order_without_duplicates() -> None:
    plan = _multi_backend_plan()
    context = BackendContext.from_plan(plan, "local")

    assert [item.ordinal for item in context.links] == [0]


def test_backend_context_rejects_empty_backend_id() -> None:
    with pytest.raises(BackendContractError) as exc_info:
        BackendContext.from_plan(_multi_backend_plan(), "   ")

    assert exc_info.value.code == "BACKEND001"


def test_backend_capabilities_helpers() -> None:
    capabilities = BackendCapabilities(
        target_kinds={"host"},
        transport_uses={"demo.transport"},
        features={"graphs"},
    )

    assert capabilities.supports_target_kind("host")
    assert not capabilities.supports_target_kind("device")
    assert capabilities.supports_transport("demo.transport")
    assert not capabilities.supports_transport("other.transport")
    assert capabilities.supports_feature("graphs")


def test_empty_capability_sets_mean_no_generic_restriction() -> None:
    capabilities = BackendCapabilities()

    assert capabilities.supports_target_kind("anything")
    assert capabilities.supports_transport("custom.transport")


def test_backend_validate_checks_target_kind() -> None:
    backend = FakeBackend(
        capabilities=BackendCapabilities(
            target_kinds={"local"},
            transport_uses={"demo.transport"},
        )
    )
    report = backend.validate_plan(_multi_backend_plan())

    assert not report.valid
    assert any(item.code == "BACKEND102" for item in report.errors)


def test_backend_validate_checks_participating_transport() -> None:
    backend = FakeBackend(
        capabilities=BackendCapabilities(
            target_kinds={"host"},
            transport_uses={"other.transport"},
        )
    )
    report = backend.validate_plan(_multi_backend_plan())

    assert not report.valid
    assert any(item.code == "BACKEND103" for item in report.errors)


def test_backend_validation_hook_is_composed_with_common_validation() -> None:
    backend = RejectingBackend()
    report = backend.validate_plan(_multi_backend_plan())

    assert not report.valid
    assert any(item.code == "FAKE001" for item in report.errors)


def test_prepare_refuses_invalid_context() -> None:
    backend = RejectingBackend()
    context = backend.context(_multi_backend_plan())

    with pytest.raises(BackendValidationError) as exc_info:
        backend.prepare(context)

    assert any(item.code == "FAKE001" for item in exc_info.value.report.errors)


def test_backend_lifecycle_contract() -> None:
    backend = FakeBackend()
    plan = _multi_backend_plan()

    prepared = backend.prepare_plan(plan)
    assert prepared.backend == "local"
    assert prepared.context.backend == "local"

    handle = backend.start(prepared)
    assert handle.execution_id == "local-1"

    running = backend.inspect(handle)
    assert running.state is BackendExecutionState.RUNNING
    assert not running.terminal

    stopped = backend.stop(handle, timeout_seconds=2.0)
    assert stopped.state is BackendExecutionState.STOPPED
    assert stopped.terminal
    assert stopped.successful
    assert stopped.details["timeout_seconds"] == 2.0


def test_backend_rejects_prepared_execution_from_another_backend() -> None:
    plan = _multi_backend_plan()
    remote_context = BackendContext.from_plan(plan, "remote")
    prepared = PreparedExecution(
        backend="remote",
        context=remote_context,
    )

    with pytest.raises(BackendContractError) as exc_info:
        FakeBackend("local").start(prepared)

    assert exc_info.value.code == "BACKEND201"


def test_backend_rejects_handle_from_another_backend() -> None:
    plan = _multi_backend_plan()
    remote_context = BackendContext.from_plan(plan, "remote")
    prepared = PreparedExecution(
        backend="remote",
        context=remote_context,
    )
    handle = BackendExecutionHandle(
        backend="remote",
        execution_id="remote-1",
        prepared=prepared,
    )

    with pytest.raises(BackendContractError) as exc_info:
        FakeBackend("local").inspect(handle)

    assert exc_info.value.code == "BACKEND204"


def test_backend_rejects_status_for_wrong_execution_id() -> None:
    class BadStatusBackend(FakeBackend):
        def _inspect(self, handle):
            return BackendExecutionStatus(
                backend=self.backend_id,
                execution_id="wrong-id",
                state=BackendExecutionState.RUNNING,
            )

    backend = BadStatusBackend()
    prepared = backend.prepare_plan(_multi_backend_plan())
    handle = backend.start(prepared)

    with pytest.raises(BackendContractError) as exc_info:
        backend.inspect(handle)

    assert exc_info.value.code == "BACKEND207"


def test_negative_stop_timeout_is_rejected() -> None:
    backend = FakeBackend()
    prepared = backend.prepare_plan(_multi_backend_plan())
    handle = backend.start(prepared)

    with pytest.raises(ValueError):
        backend.stop(handle, timeout_seconds=-1)


def test_backend_context_summary_is_stable() -> None:
    context = BackendContext.from_plan(_multi_backend_plan(), "local")

    assert context.summary == {
        "targets": 1,
        "resources": 1,
        "applications": 1,
        "graphs": 1,
        "nodes": 1,
        "connections": 0,
        "internal_links": 0,
        "inbound_links": 0,
        "outbound_links": 1,
        "artifacts": 1,
    }


def test_backend_contract_is_public_through_plyctl() -> None:
    from plyctl import (
        BackendCapabilities as PublicCapabilities,
        BackendContext as PublicContext,
        ExecutionBackend as PublicBackend,
        PreparedExecution as PublicPreparedExecution,
    )

    assert PublicCapabilities is BackendCapabilities
    assert PublicContext is BackendContext
    assert PublicBackend is ExecutionBackend
    assert PublicPreparedExecution is PreparedExecution
