from __future__ import annotations

from typing import Any


class EventTracer:
    """Low-volume lifecycle tracing; message dataplane remains untouched."""

    def __init__(
        self,
        *,
        enabled: bool,
        exporter: str,
        endpoint: str | None,
        service_name: str,
    ) -> None:
        self.tracer: Any | None = None
        self.provider: Any | None = None
        if not enabled or exporter == "none":
            return
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                ConsoleSpanExporter,
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Tracing requires `pip install plyctl[otel]`"
            ) from exc
        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        if exporter == "console":
            selected: Any = ConsoleSpanExporter()
        elif exporter == "otlp":
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "OTLP tracing requires `pip install plyctl[otel]`"
                ) from exc
            selected = OTLPSpanExporter(endpoint=endpoint)
        else:
            raise ValueError(f"Unsupported tracing exporter: {exporter}")
        provider.add_span_processor(BatchSpanProcessor(selected))
        self.provider = provider
        self.tracer = provider.get_tracer("nodrix.runtime")

    def emit(self, name: str, attributes: dict[str, Any]) -> None:
        if self.tracer is None:
            return
        clean = {
            key: value
            for key, value in attributes.items()
            if isinstance(value, (str, bool, int, float))
        }
        with self.tracer.start_as_current_span(name, attributes=clean):
            pass

    def close(self) -> None:
        if self.provider is not None:
            self.provider.shutdown()
            self.provider = None
            self.tracer = None
