"""FastAPI application factory and process lifecycle ownership."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from opentelemetry.sdk.trace.export import SpanExporter

from app.api.errors import register_exception_handlers
from app.api.middleware import CorrelationIdMiddleware, RequestMetricsMiddleware
from app.api.routes import (
    audit_router,
    formalizations_router,
    graph_router,
    health_router,
    metrics_router,
    phase3_router,
    realtime_router,
    replay_router,
)
from app.composition import Container, build_container, build_metrics
from app.config import Settings, get_settings
from app.observability.database import DatabaseInstrumentation, instrument_database
from app.observability.logging import configure_logging, register_secret_literal
from app.observability.otel import configure_tracing, instrument_app, uninstrument_app
from app.security.auth import authorize_request

__all__ = ["create_app"]

ContainerBuilder = Callable[[Settings], Awaitable[Container]]


def create_app(
    settings: Settings | None = None,
    *,
    container_builder: ContainerBuilder = build_container,
    span_exporter: SpanExporter | None = None,
) -> FastAPI:
    """Create an isolated application whose lifespan owns all selected adapters."""
    resolved_settings = settings or get_settings()
    configure_logging(level=resolved_settings.log_level, fmt=resolved_settings.log_format)
    for secret in (
        resolved_settings.postgres_password,
        resolved_settings.minio_access_key,
        resolved_settings.minio_secret_key,
    ):
        register_secret_literal(secret.get_secret_value())

    metrics = build_metrics()
    tracing = configure_tracing(
        service_name=resolved_settings.otel_service_name,
        endpoint=resolved_settings.otel_exporter_endpoint,
        code_version=resolved_settings.code_version,
        environment=resolved_settings.environment,
        span_exporter=span_exporter,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container: Container | None = None
        database_instrumentation: DatabaseInstrumentation | None = None
        try:
            container = await container_builder(resolved_settings)
            database_instrumentation = instrument_database(
                container.database.engine,
                tracer=tracing.tracer,
                metrics=metrics,
            )
            app.state.container = container
            app.state.readiness_checks = container.readiness_checks
            yield
        finally:
            if database_instrumentation is not None:
                database_instrumentation.close()
            try:
                if container is not None:
                    await container.close()
            finally:
                try:
                    uninstrument_app(app)
                finally:
                    tracing.shutdown()

    app = FastAPI(
        title="Agora API",
        version="0.1.0",
        lifespan=lifespan,
        dependencies=[Depends(authorize_request)],
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = resolved_settings
    app.state.metrics = metrics
    app.state.tracing = tracing
    app.include_router(health_router)
    app.include_router(audit_router)
    app.include_router(phase3_router)
    app.include_router(formalizations_router)
    app.include_router(graph_router)
    app.include_router(replay_router)
    app.include_router(realtime_router)
    if resolved_settings.metrics_enabled:
        app.include_router(metrics_router)
    register_exception_handlers(app)

    # Starlette's most recently added middleware is outermost. Correlation therefore
    # wraps metrics and guarantees that all downstream errors receive a trace id.
    app.add_middleware(RequestMetricsMiddleware, metrics=metrics)
    app.add_middleware(CorrelationIdMiddleware, code_version=resolved_settings.code_version)
    instrument_app(app, tracer_provider=tracing.provider)
    return app
