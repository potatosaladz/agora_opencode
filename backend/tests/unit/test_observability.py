"""Acceptance tests for logs, metrics, tracing, and SQLAlchemy telemetry."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanContext
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.prometheus.metrics import build_metrics
from app.api import create_app
from app.config import Settings
from app.observability.context import bind_request_context, clear_request_context
from app.observability.database import instrument_database
from app.observability.logging import configure_logging, get_logger, register_secret_literal
from app.observability.otel import configure_tracing
from app.ports.auth import (
    AccessTokenVerificationError,
    VerifiedPrincipal,
    WorkspaceRole,
)
from app.security import require_roles
from tests.traceability import req


@dataclass(slots=True)
class _Verifier:
    principals: dict[str, VerifiedPrincipal]

    async def verify(self, token: str) -> VerifiedPrincipal:
        try:
            return self.principals[token]
        except KeyError as exc:
            raise AccessTokenVerificationError("invalid token") from exc


class _LifecycleExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []
        self.shutdown_calls = 0

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _span_attributes(span: ReadableSpan) -> Mapping[str, Any]:
    assert span.attributes is not None
    return span.attributes


def _span_context(span: ReadableSpan) -> SpanContext:
    assert span.context is not None
    return cast(SpanContext, span.context)


def _settings(**changes: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "service_name": "api-test",
        "code_version": "test-sha",
        "event_bus": "inmemory",
        "cache": "inmemory",
        "object_store": "inmemory",
        "secret_provider": "env_file",
        "log_format": "json",
    }
    values.update(changes)
    return Settings(**values)


def _principal(role: WorkspaceRole) -> VerifiedPrincipal:
    return VerifiedPrincipal(
        subject=f"oidc|{role.lower()}",
        user_id=uuid4(),
        workspace_id=uuid4(),
        role=role,
    )


def _install_verifier(app: FastAPI, principals: dict[str, VerifiedPrincipal]) -> None:
    app.state.container.access_token_verifier = _Verifier(principals)


@req("NFR-010", "NFR-015")
def test_metrics_are_rbac_protected_and_use_route_templates() -> None:
    app = create_app(_settings())

    @app.get("/test/items/{item_id}")
    @require_roles(WorkspaceRole.VIEWER)
    async def item(item_id: UUID) -> dict[str, str]:
        return {"item_id": str(item_id)}

    item_id = uuid4()
    with TestClient(app) as client:
        _install_verifier(
            app,
            {
                "admin": _principal(WorkspaceRole.ADMIN),
                "operator": _principal(WorkspaceRole.OPERATOR),
                "viewer": _principal(WorkspaceRole.VIEWER),
            },
        )
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer viewer"}).status_code == 403
        assert (
            client.get(
                f"/test/items/{item_id}", headers={"Authorization": "Bearer viewer"}
            ).status_code
            == 200
        )
        response = client.get("/metrics", headers={"Authorization": "Bearer operator"})
        assert client.get("/metrics", headers={"Authorization": "Bearer admin"}).status_code == 200

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=")
    assert (
        'agora_http_requests_total{method="GET",route="/test/items/{item_id}",status="200"} 1.0'
        in response.text
    )
    assert "agora_http_request_duration_seconds_bucket" in response.text
    assert str(item_id) not in response.text
    assert 'route="/metrics"' not in response.text


@req("NFR-010", "NFR-015")
def test_app_instances_own_isolated_metrics_and_tracing_lifecycles() -> None:
    global_provider = trace.get_tracer_provider()
    first_exporter = _LifecycleExporter()
    second_exporter = _LifecycleExporter()
    first = create_app(_settings(), span_exporter=first_exporter)
    second = create_app(_settings(), span_exporter=second_exporter)

    assert first.state.metrics.registry is not second.state.metrics.registry
    assert first.state.tracing.provider is not second.state.tracing.provider
    assert trace.get_tracer_provider() is global_provider

    with TestClient(first) as client:
        assert client.get("/does-not-exist").status_code == 404
        assert first_exporter.shutdown_calls == 0
        assert second_exporter.shutdown_calls == 0

    assert first_exporter.shutdown_calls == 1
    assert second_exporter.shutdown_calls == 0

    with TestClient(second):
        pass

    assert first_exporter.shutdown_calls == 1
    assert second_exporter.shutdown_calls == 1


@req("NFR-010", "NFR-015")
def test_tracing_is_shutdown_when_container_startup_fails() -> None:
    exporter = _LifecycleExporter()

    async def fail_startup(_settings: Settings) -> Any:
        raise RuntimeError("startup failed")

    app = create_app(_settings(), container_builder=fail_startup, span_exporter=exporter)

    with pytest.raises(RuntimeError, match="startup failed"), TestClient(app):
        pass

    assert exporter.shutdown_calls == 1


@req("NFR-010", "NFR-015")
def test_structured_log_contains_context_and_recursively_redacts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "literal-secret-value"
    register_secret_literal(secret)
    configure_logging(level="INFO", fmt="json")
    runtime = configure_tracing(
        service_name="log-test",
        endpoint="",
        code_version="log-sha",
        environment="test",
        span_exporter=InMemorySpanExporter(),
    )
    bind_request_context(
        correlation_id="req-log-test",
        session_id="session-log-test",
        code_version="log-sha",
    )
    caplog.set_level("INFO")
    try:
        with runtime.tracer.start_as_current_span("log-parent") as span:
            get_logger("agora.test").info(
                f"message contains {secret}",
                authorization="Bearer should-not-appear",
                nested={
                    "password": "nested-password",
                    "safe": f"prefix-{secret}-suffix",
                    "values": [{"api_key": "nested-api-key"}],
                },
            )
            expected_trace_id = format(span.get_span_context().trace_id, "032x")
            expected_span_id = format(span.get_span_context().span_id, "016x")
    finally:
        clear_request_context()
        runtime.shutdown()

    payload = json.loads(caplog.records[-1].getMessage())
    assert payload["event"] == "message contains [redacted]"
    assert payload["authorization"] == "[redacted]"
    assert payload["nested"] == {
        "password": "[redacted]",
        "safe": "prefix-[redacted]-suffix",
        "values": [{"api_key": "[redacted]"}],
    }
    assert payload["correlation_id"] == "req-log-test"
    assert payload["session_id"] == "session-log-test"
    assert payload["code_version"] == "log-sha"
    assert payload["trace_id"] == expected_trace_id
    assert payload["span_id"] == expected_span_id
    assert secret not in caplog.text
    assert "nested-password" not in caplog.text
    assert "nested-api-key" not in caplog.text


@req("NFR-015")
async def test_database_instrumentation_emits_child_spans_and_transaction_metrics() -> None:
    exporter = InMemorySpanExporter()
    runtime = configure_tracing(
        service_name="database-test",
        endpoint="",
        code_version="db-sha",
        environment="test",
        span_exporter=exporter,
    )
    metrics = build_metrics()
    engine = create_async_engine("sqlite+aiosqlite://")
    instrumentation = instrument_database(engine, tracer=runtime.tracer, metrics=metrics)
    bind_request_context(
        correlation_id="req-db-test",
        session_id="session-db-test",
        code_version="db-sha",
    )
    try:
        with runtime.tracer.start_as_current_span("api request") as parent:
            parent_span_id = parent.get_span_context().span_id
            async with engine.begin() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT :private_value"), {"private_value": "must-not-be-recorded"}
                    )
                    == "must-not-be-recorded"
                )
            async with engine.connect() as connection:
                transaction = await connection.begin()
                await connection.execute(text("SELECT 1"))
                await transaction.rollback()
            async with engine.connect() as connection:
                with pytest.raises(OperationalError):
                    await connection.execute(
                        text(
                            "SELECT * FROM missing_private_table "
                            "WHERE private_value = :private_value"
                        ),
                        {"private_value": "must-not-be-recorded-error"},
                    )
                await connection.rollback()

        instrumentation.close()
        async with engine.begin() as connection:
            await connection.execute(text("SELECT 2"))
    finally:
        clear_request_context()
        instrumentation.close()
        await engine.dispose()
        runtime.shutdown()

    spans = exporter.get_finished_spans()
    exported_parent = next(span for span in spans if span.name == "api request")
    database_spans = [span for span in spans if span.name == "db SELECT"]
    assert len(database_spans) == 3
    assert all(
        _span_context(span).trace_id == _span_context(exported_parent).trace_id
        for span in database_spans
    )
    assert all(span.parent is not None for span in database_spans)
    assert all(span.parent.span_id == parent_span_id for span in database_spans if span.parent)
    assert all(_span_attributes(span)["db.system.name"] == "sqlite" for span in database_spans)
    assert all(_span_attributes(span)["db.operation.name"] == "SELECT" for span in database_spans)
    assert all(
        _span_attributes(span)["agora.correlation_id"] == "req-db-test" for span in database_spans
    )
    assert all(
        _span_attributes(span)["agora.session_id"] == "session-db-test" for span in database_spans
    )
    serialized_spans = repr(database_spans)
    assert "must-not-be-recorded" not in serialized_spans
    assert "missing_private_table" not in serialized_spans
    assert "db.statement" not in serialized_spans
    assert "db.query.text" not in serialized_spans

    exposition = metrics.render()[0].decode()
    assert (
        'agora_db_query_duration_seconds_count{operation="SELECT",outcome="success"} 2.0'
        in exposition
    )
    assert (
        'agora_db_query_duration_seconds_count{operation="SELECT",outcome="error"} 1.0'
        in exposition
    )
    assert 'agora_db_transactions_total{outcome="commit"} 1.0' in exposition
    assert 'agora_db_transactions_total{outcome="rollback"} 2.0' in exposition
