"""End-to-end proof that an authenticated API request traces into PostgreSQL."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanContext
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.api import create_app
from app.config import Settings
from app.ports.auth import VerifiedPrincipal, WorkspaceRole
from app.security import current_principal, require_roles
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL is not configured"),
]


@dataclass(slots=True)
class _Verifier:
    principal: VerifiedPrincipal

    async def verify(self, _token: str) -> VerifiedPrincipal:
        return self.principal


def _span_attributes(span: ReadableSpan) -> Mapping[str, Any]:
    assert span.attributes is not None
    return span.attributes


def _span_context(span: ReadableSpan) -> SpanContext:
    assert span.context is not None
    return cast(SpanContext, span.context)


@req("NFR-015")
def test_authenticated_api_request_is_traced_through_postgresql() -> None:
    assert _DATABASE_URL is not None
    url = make_url(_DATABASE_URL)
    assert url.host is not None
    assert url.database is not None
    assert url.username is not None
    settings = Settings(
        environment="test",
        service_name="observability-integration",
        code_version="integration-sha",
        event_bus="inmemory",
        cache="inmemory",
        object_store="inmemory",
        secret_provider="env_file",
        postgres_host=url.host,
        postgres_port=url.port or 5432,
        postgres_db=url.database,
        postgres_user=url.username,
        postgres_password=SecretStr(url.password or ""),
    )
    exporter = InMemorySpanExporter()
    app = create_app(settings, span_exporter=exporter)

    @app.get("/test/observability/database")
    @require_roles(WorkspaceRole.ADMIN)
    async def database_probe(request: Request) -> dict[str, int]:
        principal = current_principal(request)
        async with request.app.state.container.database.session(principal.workspace_id) as session:
            return {"value": int(await session.scalar(text("SELECT 1")))}

    principal = VerifiedPrincipal(
        subject="oidc|observability-admin",
        user_id=uuid4(),
        workspace_id=uuid4(),
        role=WorkspaceRole.ADMIN,
    )
    correlation_id = "req-api-database-trace"
    with TestClient(app) as client:
        app.state.container.access_token_verifier = _Verifier(principal)
        response = client.get(
            "/test/observability/database",
            headers={
                "Authorization": "Bearer integration-token",
                "X-Request-Id": correlation_id,
            },
        )
        metrics = client.get("/metrics", headers={"Authorization": "Bearer integration-token"})

    assert response.status_code == 200
    assert response.json() == {"value": 1}
    assert response.headers["X-Request-Id"] == correlation_id
    assert metrics.status_code == 200
    assert (
        'agora_http_requests_total{method="GET",route="/test/observability/database",status="200"} '
        "1.0" in metrics.text
    )
    assert (
        'agora_db_query_duration_seconds_count{operation="SELECT",outcome="success"} 2.0'
        in metrics.text
    )
    assert 'agora_db_transactions_total{outcome="commit"} 1.0' in metrics.text

    spans = exporter.get_finished_spans()
    server_span = next(
        span
        for span in spans
        if _span_attributes(span).get("http.route") == "/test/observability/database"
    )
    database_spans = [span for span in spans if span.name == "db SELECT"]
    assert len(database_spans) == 2
    assert all(
        _span_context(span).trace_id == _span_context(server_span).trace_id
        for span in database_spans
    )
    assert all(span.parent is not None for span in database_spans)
    assert all(
        span.parent.span_id == _span_context(server_span).span_id
        for span in database_spans
        if span.parent is not None
    )
    assert _span_attributes(server_span)["agora.correlation_id"] == correlation_id
    assert _span_attributes(server_span)["service.version"] == "integration-sha"
    assert all(
        _span_attributes(span)["agora.correlation_id"] == correlation_id for span in database_spans
    )
    assert all(
        _span_attributes(span)["service.version"] == "integration-sha" for span in database_spans
    )
    assert all("db.statement" not in _span_attributes(span) for span in database_spans)
    assert all("db.query.text" not in _span_attributes(span) for span in database_spans)
