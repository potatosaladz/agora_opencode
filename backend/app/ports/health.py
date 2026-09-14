"""Health vocabulary shared by every port and by `/health` and `/ready`.

`docs/DEPLOYMENT.md` requires liveness and readiness to be distinguishable. Liveness is
"this process is not wedged"; readiness is "I can reach what I need to serve traffic".
A dependency that is down makes a service *not ready*, never *not live*, because
restarting a healthy process cannot fix Postgres.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

__all__ = ["ComponentHealth", "HealthStatus"]


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class ComponentHealth:
    """The health of one dependency, with enough detail to act on.

    `details` must never contain a credential or a connection string — it is rendered by
    `/ready`, which is an unauthenticated endpoint by design (docs/SECURITY.md).
    """

    __slots__ = ("details", "name", "status")

    def __init__(
        self,
        name: str,
        status: HealthStatus,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.status = status
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "details": self.details}
