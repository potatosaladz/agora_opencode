"""Request-scoped correlation context.

`docs/ARCHITECTURE.md` §9.4: every span, log line and event carries `session_id`,
`correlation_id` and `code_version`. ContextVars are the only mechanism that survives
`await` correctly in asyncio without threading arguments through every signature.
"""

from __future__ import annotations

from contextvars import ContextVar

__all__ = [
    "bind_request_context",
    "clear_request_context",
    "current_code_version",
    "current_correlation_id",
    "current_session_id",
]

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("session_id", default=None)
_code_version: ContextVar[str] = ContextVar("code_version", default="dev")


def current_correlation_id() -> str | None:
    return _correlation_id.get()


def current_session_id() -> str | None:
    return _session_id.get()


def current_code_version() -> str:
    return _code_version.get()


def bind_request_context(*, correlation_id: str, session_id: str | None, code_version: str) -> None:
    _correlation_id.set(correlation_id)
    _session_id.set(session_id)
    _code_version.set(code_version)


def clear_request_context() -> None:
    _correlation_id.set(None)
    _session_id.set(None)
    _code_version.set("dev")
