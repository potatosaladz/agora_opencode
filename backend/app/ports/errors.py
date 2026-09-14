"""Port error hierarchy. `docs/PORTS.md` §0: no raw driver exception escapes an adapter.

Adapters catch their SDK's exceptions at the boundary and re-raise one of these. The
distinction is not cosmetic: `TransientPortError` is what the workflow layer is allowed to
retry, and `PermanentPortError` is what must fail fast and be surfaced. Adapters themselves
never retry (`docs/PORTS.md` §0, "Retries").
"""

from __future__ import annotations

__all__ = [
    "IntegrityObjectError",
    "NotFoundObjectError",
    "PermanentPortError",
    "PortError",
    "TransientPortError",
]


class PortError(Exception):
    """Base for every failure crossing a port boundary."""

    def __init__(self, message: str, *, port: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.port = port
        if cause is not None:
            self.__cause__ = cause


class TransientPortError(PortError):
    """The same call may succeed later: timeout, connection reset, 5xx, backpressure."""


class PermanentPortError(PortError):
    """The same call will fail identically: bad credentials, missing bucket, denied ACL."""


class NotFoundObjectError(PermanentPortError):
    """The requested object-store bucket or key does not exist."""


class IntegrityObjectError(PermanentPortError):
    """Stored bytes do not match their declared immutable digest or size."""
