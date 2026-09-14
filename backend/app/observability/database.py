"""SQLAlchemy event instrumentation without recording statements or parameters."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer
from sqlalchemy import event
from sqlalchemy.engine import Connection, ExceptionContext
from sqlalchemy.ext.asyncio import AsyncEngine

from app.observability.context import (
    current_code_version,
    current_correlation_id,
    current_session_id,
)
from app.observability.metrics import Metrics

__all__ = ["DatabaseInstrumentation", "instrument_database"]

_QUERY_STACK = "agora_observability_query_stack"


def _operation(statement: str) -> str:
    token = statement.lstrip().partition(" ")[0].upper()
    return token if token in {"DELETE", "INSERT", "SELECT", "UPDATE"} else "OTHER"


@dataclass(slots=True)
class DatabaseInstrumentation:
    """Removable event hooks attached to one async engine."""

    engine: AsyncEngine
    listeners: tuple[tuple[str, Any], ...]
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for event_name, listener in self.listeners:
            event.remove(self.engine.sync_engine, event_name, listener)


def instrument_database(
    engine: AsyncEngine, *, tracer: Tracer, metrics: Metrics
) -> DatabaseInstrumentation:
    """Attach query spans, duration metrics, and transaction outcome counters."""

    def before_cursor_execute(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        operation = _operation(statement)
        attributes = {
            "db.system.name": engine.dialect.name,
            "db.operation.name": operation,
            "service.version": current_code_version(),
        }
        correlation_id = current_correlation_id()
        session_id = current_session_id()
        if correlation_id is not None:
            attributes["agora.correlation_id"] = correlation_id
        if session_id is not None:
            attributes["agora.session_id"] = session_id
        span = tracer.start_span(
            f"db {operation}",
            kind=SpanKind.CLIENT,
            attributes=attributes,
        )
        stack: list[tuple[float, str, Span]] = connection.info.setdefault(_QUERY_STACK, [])
        stack.append((time.perf_counter(), operation, span))

    def finish(connection: Connection, *, outcome: str, error: BaseException | None = None) -> None:
        stack: list[tuple[float, str, Span]] = connection.info.get(_QUERY_STACK, [])
        if not stack:
            return
        started, operation, span = stack.pop()
        metrics.db_query_latency.labels(operation, outcome).observe(time.perf_counter() - started)
        if error is not None:
            # Driver exception messages may contain SQL fragments or values. Record only the
            # bounded type so error telemetry cannot become a statement/parameter side channel.
            span.add_event(
                "exception",
                attributes={
                    "exception.type": type(error).__name__,
                    "exception.escaped": True,
                },
            )
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
        span.end()

    def after_cursor_execute(
        connection: Connection,
        _cursor: object,
        _statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        finish(connection, outcome="success")

    def handle_error(context: ExceptionContext) -> None:
        if context.connection is not None:
            finish(context.connection, outcome="error", error=context.original_exception)

    def commit(_connection: Connection) -> None:
        metrics.db_transactions.labels("commit").inc()

    def rollback(_connection: Connection) -> None:
        metrics.db_transactions.labels("rollback").inc()

    listeners = (
        ("before_cursor_execute", before_cursor_execute),
        ("after_cursor_execute", after_cursor_execute),
        ("handle_error", handle_error),
        ("commit", commit),
        ("rollback", rollback),
    )
    for event_name, listener in listeners:
        event.listen(engine.sync_engine, event_name, listener)
    return DatabaseInstrumentation(engine=engine, listeners=listeners)
