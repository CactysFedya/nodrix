"""Transport-aware composition of the M2 local execution backend."""

from __future__ import annotations

from contextlib import nullcontext

from ..manifest import dump_manifest
from .backend import BackendContext, BackendDiagnostic, PreparedExecution
from .local_backend import (
    LocalBackend as InProcessLocalBackend,
    LocalPreparedPayload,
    _activate_local_project,
    _compile_local_project,
    lower_local_context,
)
from .transport import transport_runtime
from .transport_lowering import lower_transport_boundaries


class TransportLocalBackend(InProcessLocalBackend):
    """Run an in-process scope with registered boundary transports."""

    def _validate(self, context: BackendContext):
        diagnostics = [
            item
            for item in super()._validate(context)
            if item.code != "LOCAL101"
        ]
        for link in (*context.inbound_links, *context.outbound_links):
            adapter = transport_runtime(link.transport_uses)
            if adapter is None:
                diagnostics.append(
                    BackendDiagnostic(
                        level="error",
                        code="LOCAL103",
                        path=f"links[{link.ordinal}].uses",
                        message=(
                            "no runtime transport adapter is registered for "
                            f"{link.transport_uses!r}"
                        ),
                    )
                )
                continue
            try:
                adapter.validate(link.parameters)
            except ValueError as exc:
                diagnostics.append(
                    BackendDiagnostic(
                        level="error",
                        code="LOCAL104",
                        path=f"links[{link.ordinal}].parameters",
                        message=str(exc),
                    )
                )
        return diagnostics

    def _prepare(self, context: BackendContext) -> PreparedExecution:
        lowering = lower_transport_boundaries(
            context,
            lower_local_context(context),
        )

        project = None
        if self.project_path is not None:
            project = _compile_local_project(self.project_path)
            project_root = project.root
        else:
            project_root = self.working_directory

        generated_dir = project_root / ".nodrix" / "system-generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        scope_suffix = f"-{self.scope_name}" if self.scope_name else ""
        manifest_path = generated_dir / (
            f"{context.plan.system}-{context.plan.system_sha256[:12]}"
            f"{scope_suffix}-local.yaml"
        )
        dump_manifest(lowering.manifest, manifest_path)

        runtime = self.runtime_factory(
            lowering.manifest,
            manifest_path,
            self.run_root,
        )
        activation = (
            _activate_local_project(project)
            if project is not None
            else nullcontext()
        )
        with activation:
            build = getattr(runtime, "build", None)
            if callable(build):
                build()

        return PreparedExecution(
            backend=self.backend_id,
            context=context,
            payload=LocalPreparedPayload(
                lowering=lowering,
                manifest_path=manifest_path,
                runtime=runtime,
                project=project,
            ),
            metadata={
                "manifest_path": str(manifest_path),
                "legacy_snapshot": lowering.generated_from_legacy_snapshot,
                "node_aliases": dict(lowering.node_aliases),
                "transport_links": len(context.inbound_links)
                + len(context.outbound_links),
            },
        )


__all__ = ["TransportLocalBackend"]
