"""Structured logging with secret redaction baked in, not bolted on.

`docs/SECURITY.md` and `docs/TESTING.md` both require that logs never contain
credentials or raw provider payloads. The usual way to satisfy that is a rule telling
people not to log secrets, which fails the first time someone logs a whole settings
object. Here redaction is a processor on every logger, so the mistake is impossible to
make quietly:

* any value whose *key* looks like a secret is replaced with `[redacted]`;
* any string value that matches a registered secret *literal* is scrubbed, which catches
  a password interpolated into a message or a URL.

`get_logger` returns a structlog logger. Console output in dev, JSON elsewhere, because
a human reads the first and Loki parses the second.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping
from typing import Any, cast

import structlog

__all__ = ["configure_logging", "get_logger", "redact_text", "register_secret_literal"]

_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|credential|access[_-]?key)"
)
_REDACTED = "[redacted]"

#: Secret literals registered at startup, scrubbed from every string that passes through
#: the logging pipeline. Populated by the composition root via `register_secret_literal`.
_secret_literals: set[str] = set()

_configured: tuple[str, str] | None = None


def register_secret_literal(value: str) -> None:
    """Declare a string a secret so it can never be emitted by a log line."""
    if value and len(value) >= 6:
        _secret_literals.add(value)


def redact_text(text: str) -> str:
    """Scrub every registered secret literal from free text.

    Also used by the LLM adapter before storing a raw request/response artifact
    (`docs/PORTS.md` §1: raw payloads are stored "secret-redacted").
    """
    result = text
    for literal in _secret_literals:
        result = result.replace(literal, _REDACTED)
    return result


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            key: _REDACTED if _SECRET_KEY_PATTERN.search(str(key)) else _scrub_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(item) for item in value)
    return value


def _scrub_secrets(
    _logger: Any, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    for key in list(event_dict):
        if _SECRET_KEY_PATTERN.search(key):
            if event_dict[key] not in (None, ""):
                event_dict[key] = _REDACTED
        else:
            event_dict[key] = _scrub_value(event_dict[key])
    event_dict["event"] = redact_text(str(event_dict.get("event", "")))
    return event_dict


def _add_correlation(
    _logger: Any, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Attach the request-scoped correlation id so a session can be traced end to end.

    `docs/ARCHITECTURE.md` §9.4 requires `session_id`, `correlation_id` and `code_version`
    on every log line; the first two arrive via contextvars set by the request middleware.
    """
    from app.observability.context import (
        current_code_version,
        current_correlation_id,
        current_session_id,
    )

    event_dict.setdefault("correlation_id", current_correlation_id())
    event_dict.setdefault("session_id", current_session_id())
    event_dict.setdefault("code_version", current_code_version())
    try:
        from opentelemetry import trace

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            event_dict.setdefault("trace_id", format(span_context.trace_id, "032x"))
            event_dict.setdefault("span_id", format(span_context.span_id, "016x"))
    except ImportError:  # pragma: no cover - OpenTelemetry is optional to logging itself.
        pass
    return event_dict


def configure_logging(*, level: str = "INFO", fmt: str = "json") -> None:
    """Idempotent. Safe to call from an app factory and again from a test fixture."""
    global _configured
    configuration = (level, fmt)
    if _configured == configuration:
        return

    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _add_correlation,
        _scrub_secrets,
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level, logging.INFO)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="%(message)s")
    logging.getLogger().setLevel(getattr(logging, level, logging.INFO))
    _configured = configuration


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, configuring the root pipeline on first use."""
    if _configured is None:
        configure_logging()
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
