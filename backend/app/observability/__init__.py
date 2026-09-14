"""Observability: structured logs, metrics, traces. `docs/OBSERVABILITY.md`."""

from app.observability.context import (
    bind_request_context,
    clear_request_context,
    current_correlation_id,
    current_session_id,
)
from app.observability.logging import (
    configure_logging,
    get_logger,
    redact_text,
    register_secret_literal,
)

__all__ = [
    "bind_request_context",
    "clear_request_context",
    "configure_logging",
    "current_correlation_id",
    "current_session_id",
    "get_logger",
    "redact_text",
    "register_secret_literal",
]
