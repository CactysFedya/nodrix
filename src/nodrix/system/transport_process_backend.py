"""Transport-aware composition of the M3 process-isolation backend.

M3's :class:`~nodrix.system.process_backend.ProcessBackend` deliberately owns
only process lifecycle.  M4 layers boundary transport validation and lowering
on top without coupling process-tree semantics to a particular data transport.
The inherited backend id remains ``process``.
"""

from __future__ import annotations

from dataclasses import replace

from ..manifest import dump_manifest
from .backend import BackendContext, BackendDiagnostic, PreparedExecution
from .local_backend import lower_local_context
from .process_backend import ProcessBackend as IsolatedProcessBackend
from .transport import transport_runtime
from .transport_lowering import lower_transport_boundaries


class TransportProcessBackend(IsolatedProcessBackend):
    """Run a process-isolated scope with registered boundary transports."""

    def _validate(self, context: BackendContext):
        diagnostics: list[BackendDiagnostic] = []
        for link in (*context.inbound_links, *context.outbound_links):
            adapter = transport_runtime(link.transport_uses)
            if adapter is None:
                diagnostics.append(
                    BackendDiagnostic(
                        level="error",
                        code="PROCESS101",
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
                        code="PROCESS102",
                        path=f"links[{link.ordinal}].parameters",
                        message=str(exc),
                    )
                )
        return diagnostics

    def _prepare(self, context: BackendContext) -> PreparedExecution:
        # Reuse the fully-qualified M3 preparation contract for scope-safe paths
        # and ProcessPreparedPayload, then replace its data-plane manifest with
        # the M4 transport-aware lowering. This keeps process lifecycle frozen.
        prepared = super()._prepare(context)
        lowering = lower_transport_boundaries(
            context,
            lower_local_context(context),
        )
        dump_manifest(lowering.manifest, prepared.payload.manifest_path)
        return replace(
            prepared,
            metadata={
                **prepared.metadata,
                "transport_links": len(context.inbound_links)
                + len(context.outbound_links),
            },
        )


__all__ = ["TransportProcessBackend"]
