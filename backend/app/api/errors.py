"""`application/problem+json` — the only error body the API ever returns.

Shape and codes: `docs/API_CONTRACTS.md` §6. Rules implemented here:

* A 500 never leaks an exception message, a SQL fragment or a path. `trace_id` is the only
  handle, which is what makes the log correlation in `app/observability` load-bearing.
* `NOT_FOUND` is produced for both "absent" and "hidden by RLS". The application layer
  raises the same error for both, so existence never leaks through a status code.
* `retryable` is derived from the code table, never set by hand at a call site, so a
  client's backoff decision cannot disagree with the taxonomy.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.common.errors import (
    DomainError,
    ErrorCode,
    Internal,
    NotFound,
    UnknownField,
    ValidationFailed,
)
from app.observability.logging import get_logger

__all__ = ["ProblemDetails", "register_exception_handlers"]

_LOG = get_logger("agora.api.errors")

PROBLEM_CONTENT_TYPE = "application/problem+json"


class ProblemDetails(BaseModel):
    """RFC 9457 plus the two fields this platform adds: `code` and `retryable`."""

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    code: str
    detail: str
    instance: str | None = None
    trace_id: str | None = None
    retryable: bool = False


def _exception_for(code: ErrorCode) -> type[DomainError]:
    """Resolve a code to its exception class by scanning subclasses.

    A hand-maintained registry here would drift from `app/common/errors.py` the moment
    someone added a code. Deriving it means there is exactly one list to keep correct.
    """
    for subclass in _all_subclasses(DomainError):
        if getattr(subclass, "code", None) is code:
            return subclass
    return Internal


def _all_subclasses(cls: type) -> list[type]:
    found: list[type] = []
    for child in cls.__subclasses__():
        found.append(child)
        found.extend(_all_subclasses(child))
    return found


def _problem(request: Request, error: DomainError) -> JSONResponse:
    problem = ProblemDetails(
        type=error.problem_urn,
        title=error.title,
        status=error.status,
        code=error.code.value,
        detail=error.detail,
        instance=str(request.url.path),
        trace_id=getattr(request.state, "correlation_id", None),
        retryable=error.retryable,
    )
    body: dict[str, Any] = problem.model_dump()
    body.update(error.extras)

    headers: dict[str, str] = {}
    if error.code is ErrorCode.AUTH_REQUIRED:
        headers["WWW-Authenticate"] = "Bearer"
    if problem.trace_id is not None:
        headers["X-Request-Id"] = problem.trace_id
    if error.code is ErrorCode.RATE_LIMITED and "retry_after_s" in error.extras:
        headers["Retry-After"] = str(int(error.extras["retry_after_s"]))
    return JSONResponse(
        status_code=error.status,
        content=body,
        media_type=PROBLEM_CONTENT_TYPE,
        headers=headers,
    )


_HTTP_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.VALIDATION_FAILED,
    401: ErrorCode.AUTH_REQUIRED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.FORBIDDEN,
    409: ErrorCode.VERSION_CONFLICT,
    413: ErrorCode.VALIDATION_FAILED,
    422: ErrorCode.VALIDATION_FAILED,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.PORT_UNAVAILABLE,
}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler. Called by the app factory."""

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        log = _LOG.error if exc.status >= 500 else _LOG.info
        log("domain_error", code=exc.code.value, detail=exc.detail)
        return _problem(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _request_invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # §6: "schema violation; errors[] lists JSON pointers".
        errors = [
            {
                "pointer": "/" + "/".join(str(part) for part in err.get("loc", ())),
                "message": str(err.get("msg", "invalid")),
                "type": str(err.get("type", "value_error")),
            }
            for err in exc.errors()
        ]
        error_type: type[DomainError] = (
            UnknownField
            if any(str(error.get("type")) == "extra_forbidden" for error in exc.errors())
            else ValidationFailed
        )
        return _problem(request, error_type("request failed validation", extras={"errors": errors}))

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # A router 404 and an RLS 404 produce byte-identical bodies, so a probe cannot
        # tell a missing resource from a forbidden one.
        code = _HTTP_STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL)
        if code is ErrorCode.INTERNAL:
            error: DomainError = Internal("an unexpected error occurred")
            _LOG.error("http_500", status=exc.status_code)
        else:
            error = _exception_for(code)(str(exc.detail))
        return _problem(request, error)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # The message stays in the log; the client gets a trace id and nothing else.
        _LOG.error("unhandled_exception", error_type=type(exc).__name__, detail=str(exc))
        return _problem(request, Internal("an unexpected error occurred"))


def not_found(resource: str) -> NotFound:
    """Convenience so route handlers do not import the error classes directly."""
    return NotFound(f"{resource} not found")
