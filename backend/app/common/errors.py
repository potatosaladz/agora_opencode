"""The error taxonomy. Single source of truth for `docs/API_CONTRACTS.md` §6.

Every value the API refuses is raised as a `DomainError` subclass carrying an `ErrorCode`;
`app/api/errors.py` is the only place that turns one into an
`application/problem+json` body. Nothing below this line knows about HTTP except through
the `status` on the code, which keeps domain and application layers transport-free.

The codes are **additive forever**: a code is never redefined and never removed while a
released client exists (NFR-014). `tests/contracts/test_error_taxonomy.py` proves each
code here is documented and reachable, which is the contract in §8.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

__all__ = [
    "BudgetExceeded",
    "CommitForbidden",
    "DomainError",
    "ErrorCode",
    "Forbidden",
    "Internal",
    "NotAuthenticated",
    "NotFound",
    "PortUnavailable",
    "ProvenanceMissing",
    "RagFailed",
    "RateLimited",
    "UnknownField",
    "ValidationFailed",
    "VersionConflict",
    "WorkflowUnreachable",
]


class ErrorCode(StrEnum):
    """A stable machine-readable code, its HTTP status, and whether retrying can help."""

    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    COMMIT_FORBIDDEN = "COMMIT_FORBIDDEN"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    IDEMPOTENCY_REPLAY = "IDEMPOTENCY_REPLAY"
    NOT_FOUND = "NOT_FOUND"
    PROVENANCE_MISSING = "PROVENANCE_MISSING"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    PORT_UNAVAILABLE = "PORT_UNAVAILABLE"
    RAG_FAILED = "RAG_FAILED"
    WORKFLOW_UNREACHABLE = "WORKFLOW_UNREACHABLE"
    INTERNAL = "INTERNAL"


#: code -> (http status, retryable, human title). Mirrors API_CONTRACTS.md §6 row for row.
_ERROR_META: dict[ErrorCode, tuple[int, bool, str]] = {
    ErrorCode.VALIDATION_FAILED: (400, False, "Validation failed"),
    ErrorCode.UNKNOWN_FIELD: (400, False, "Unknown field"),
    ErrorCode.AUTH_REQUIRED: (401, False, "Authentication required"),
    ErrorCode.FORBIDDEN: (403, False, "Forbidden"),
    ErrorCode.COMMIT_FORBIDDEN: (403, False, "Commit forbidden"),
    ErrorCode.VERSION_CONFLICT: (409, False, "Version conflict"),
    # Not an error body: the original response is replayed instead. Listed so the
    # taxonomy is complete and the code is reachable from the idempotency middleware.
    ErrorCode.IDEMPOTENCY_REPLAY: (200, False, "Idempotency replay"),
    # 404 covers "absent" *and* "hidden by RLS" - deliberately indistinguishable, so a
    # denial never leaks the existence of a resource.
    ErrorCode.NOT_FOUND: (404, False, "Not found"),
    ErrorCode.PROVENANCE_MISSING: (422, False, "Provenance missing"),
    ErrorCode.BUDGET_EXCEEDED: (402, False, "Budget exceeded"),
    ErrorCode.RATE_LIMITED: (429, True, "Rate limited"),
    ErrorCode.PORT_UNAVAILABLE: (503, True, "Port unavailable"),
    ErrorCode.RAG_FAILED: (503, True, "Retrieval failed"),
    ErrorCode.WORKFLOW_UNREACHABLE: (503, True, "Workflow engine unreachable"),
    ErrorCode.INTERNAL: (500, False, "Internal error"),
}


def _meta(code: ErrorCode) -> tuple[int, bool, str]:
    try:
        return _ERROR_META[code]
    except KeyError as exc:  # pragma: no cover - guards a member added without metadata
        raise RuntimeError(f"ErrorCode {code} has no entry in _ERROR_META") from exc


class DomainError(Exception):
    """Base class for every deliberate failure in the platform.

    `extras` is merged into the problem document, which is how `errors[]` pointers,
    `current_version` and `degraded` reach the client without inventing new codes.
    """

    code: ErrorCode

    def __init__(
        self,
        detail: str,
        *,
        extras: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extras: dict[str, Any] = dict(extras or {})
        if cause is not None:
            self.__cause__ = cause

    @property
    def status(self) -> int:
        return _meta(self.code)[0]

    @property
    def retryable(self) -> bool:
        return _meta(self.code)[1]

    @property
    def title(self) -> str:
        return _meta(self.code)[2]

    @property
    def problem_urn(self) -> str:
        """The `type` of the problem document. A stable slug, never a live URL."""
        return f"https://example.invalid/errors/{self.code.name.lower()}"


class ValidationFailed(DomainError):
    code = ErrorCode.VALIDATION_FAILED


class UnknownField(DomainError):
    code = ErrorCode.UNKNOWN_FIELD


class NotAuthenticated(DomainError):
    code = ErrorCode.AUTH_REQUIRED


class Forbidden(DomainError):
    code = ErrorCode.FORBIDDEN


class CommitForbidden(DomainError):
    """A principal class may not commit this transition (docs/ARCHITECTURE.md V-2)."""

    code = ErrorCode.COMMIT_FORBIDDEN


class VersionConflict(DomainError):
    code = ErrorCode.VERSION_CONFLICT

    def __init__(self, detail: str, *, current_version: int) -> None:
        super().__init__(detail, extras={"current_version": current_version})


class NotFound(DomainError):
    code = ErrorCode.NOT_FOUND


class ProvenanceMissing(DomainError):
    code = ErrorCode.PROVENANCE_MISSING


class BudgetExceeded(DomainError):
    code = ErrorCode.BUDGET_EXCEEDED


class RateLimited(DomainError):
    code = ErrorCode.RATE_LIMITED

    def __init__(self, detail: str, *, retry_after_s: float = 1.0) -> None:
        super().__init__(detail, extras={"retry_after_s": retry_after_s})


class PortUnavailable(DomainError):
    """An adapter failed. `port` names it, so a degraded response says what is degraded."""

    code = ErrorCode.PORT_UNAVAILABLE

    def __init__(self, detail: str, *, port: str) -> None:
        super().__init__(detail, extras={"degraded": port})


class RagFailed(DomainError):
    """Retrieval is broken. Distinct from an empty result set - FR-409."""

    code = ErrorCode.RAG_FAILED


class WorkflowUnreachable(DomainError):
    code = ErrorCode.WORKFLOW_UNREACHABLE


class Internal(DomainError):
    code = ErrorCode.INTERNAL
