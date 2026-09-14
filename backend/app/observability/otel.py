"""Application-owned OpenTelemetry setup with no process-global provider mutation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Tracer

from app.observability.logging import get_logger

__all__ = ["TracingRuntime", "configure_tracing", "instrument_app", "uninstrument_app"]

_LOG = get_logger("agora.observability.otel")


@dataclass(slots=True)
class TracingRuntime:
    """Tracing resources owned by exactly one application instance."""

    provider: TracerProvider
    tracer: Tracer
    exporter_attached: bool
    _closed: bool = field(default=False, init=False, repr=False)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.provider.shutdown()


def configure_tracing(
    *,
    service_name: str,
    endpoint: str,
    code_version: str,
    environment: str,
    span_exporter: SpanExporter | None = None,
) -> TracingRuntime:
    """Build a provider for one app; never replace OpenTelemetry's global provider."""
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": code_version,
            "deployment.environment.name": environment,
        }
    )
    provider = TracerProvider(resource=resource)

    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
        attached = True
    elif endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        traces_endpoint = f"{endpoint.rstrip('/')}/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_endpoint)))
        attached = True
        _LOG.info("tracing_enabled", endpoint=endpoint)
    else:
        attached = False
        _LOG.info("tracing_console_only", reason="no exporter endpoint configured")

    return TracingRuntime(
        provider=provider,
        tracer=provider.get_tracer("agora", code_version),
        exporter_attached=attached,
    )


def instrument_app(app: Any, *, tracer_provider: TracerProvider) -> None:
    """FastAPI instrumentation. Skips /health and /metrics so probes do not drown traces."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        excluded_urls="^/health$,^/ready$,^/metrics$",
        exclude_spans=["receive", "send"],
    )


def uninstrument_app(app: Any) -> None:
    """Remove instrumentation installed on one application during lifespan cleanup."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.uninstrument_app(app)
