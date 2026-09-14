"""Request middleware: correlation, timing, RED metrics.

`docs/ARCHITECTURE.md` §9.4 requires that every log line, span and event carry
`correlation_id`, `session_id` and `code_version`. This module is where the first and
third are established for an inbound request; `session_id` is bound later by the route
that resolves the session, because a session id in a URL is not trusted until it is
authorised.

Inbound `X-Request-Id` is honoured rather than generated when present, so a request that
crossed a proxy or a worker keeps one identity instead of two.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.common.ids import uuid7
from app.observability.context import bind_request_context, clear_request_context
from app.observability.logging import get_logger
from app.observability.metrics import Metrics

__all__ = ["CorrelationIdMiddleware", "RequestMetricsMiddleware"]

_LOG = get_logger("agora.api.request")

REQUEST_ID_HEADER = "X-Request-Id"


def _route_label(request: Request) -> str:
    """The matched template, not the raw path.

    `/api/v1/sessions/ses_01abc` and `/api/v1/sessions/ses_01def` must collapse to one
    label, or the histogram becomes an unbounded-cardinality copy of the request log and
    Prometheus becomes the thing that is down.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return str(path)
    if request.url.path.startswith("/api/"):
        return "unmatched"
    return "other"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Establish request identity before anything can log, and echo it back."""

    def __init__(self, app: object, *, code_version: str = "dev") -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._code_version = code_version

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = request.headers.get(REQUEST_ID_HEADER) or f"req_{uuid7().hex}"
        bind_request_context(
            correlation_id=correlation_id, session_id=None, code_version=self._code_version
        )
        request.state.correlation_id = correlation_id
        from opentelemetry import trace

        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute("agora.correlation_id", correlation_id)
            span.set_attribute("service.version", self._code_version)
        try:
            response = await call_next(request)
        finally:
            clear_request_context()
        response.headers[REQUEST_ID_HEADER] = correlation_id
        return response


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """Count and time every request. Excludes probes so health checks do not skew latency."""

    EXEMPT_PATHS = frozenset({"/health", "/ready", "/metrics"})

    def __init__(self, app: object, *, metrics: Metrics) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._metrics = metrics

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The exception handlers turn this into a 500 problem document; the metric is
            # recorded here because a crash must not be invisible in the RED dashboard.
            self._metrics.http_requests.labels(request.method, _route_label(request), "500").inc()
            self._metrics.http_latency.labels(request.method, _route_label(request)).observe(
                time.perf_counter() - started
            )
            raise

        duration = time.perf_counter() - started
        route = _route_label(request)
        status = str(response.status_code)
        self._metrics.http_requests.labels(request.method, route, status).inc()
        self._metrics.http_latency.labels(request.method, route).observe(duration)

        log = _LOG.warning if response.status_code >= 500 else _LOG.info
        log(
            "request",
            method=request.method,
            route=route,
            status=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )
        response.headers["X-Process-Time-Ms"] = f"{duration * 1000:.2f}"
        return response
