"""Liveness and readiness. `docs/DEPLOYMENT.md` §health, `docs/PORTS.md` §health vocabulary.

The two endpoints answer different questions and must never be collapsed into one:

* `/health` — *liveness*. "Is this process un-wedged?" It deliberately checks **no**
  dependencies. If it consulted Postgres, a database outage would make Swarm kill and
  restart every API replica, converting one outage into a thundering herd of cold starts
  and turning a recoverable dependency failure into a total one.
* `/ready` — *readiness*. "Can this replica serve traffic?" Every registered
  dependency answers. A single `down` makes the whole response `down` and the status 503,
  which is the only signal the orchestrator has to stop routing here.

Neither is authenticated: they are scraped by the orchestrator and by Prometheus, which
have no user token. That is why the body carries no connection strings, no versions of
anything sensitive, and no secret — enforced by `tests/unit/test_health.py`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.observability.logging import get_logger
from app.ports.health import HealthStatus
from app.security import public_route

__all__ = ["router"]

_LOG = get_logger("agora.api.health")

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe", response_model=None)
@public_route
async def health(request: Request) -> dict[str, Any]:
    """Process-level liveness. No dependency is consulted, on purpose."""
    settings = request.app.state.settings
    return {
        "status": HealthStatus.OK.value,
        "service": settings.service_name,
        "version": settings.code_version,
    }


@router.get("/ready", summary="Readiness probe", response_model=None)
@public_route
async def ready(request: Request) -> JSONResponse:
    """Aggregate every registered dependency check into one verdict."""
    settings = request.app.state.settings
    checks: dict[str, Any] = request.app.state.readiness_checks

    components: dict[str, Any] = {}
    worst = HealthStatus.OK
    # Checks run concurrently: a 2s timeout on three dependencies must cost 2s, not 6s,
    # or the probe interval has to be longer than the sum of every dependency's worst case.
    import asyncio

    results = await asyncio.gather(
        *(_run_check(name, check) for name, check in checks.items()), return_exceptions=False
    )
    for name, status, details in results:
        components[name] = {"status": status.value, "details": details}
        if _SEVERITY[status] > _SEVERITY[worst]:
            worst = status

    body = {
        "status": worst.value,
        "service": settings.service_name,
        "version": settings.code_version,
        "components": components,
    }
    request.app.state.metrics.readiness.set(1 if worst is HealthStatus.OK else 0)

    if worst is HealthStatus.DOWN:
        _LOG.warning("readiness_down", components=_down_names(components))
    return JSONResponse(status_code=200 if worst is not HealthStatus.DOWN else 503, content=body)


async def _run_check(name: str, check: Any) -> tuple[str, HealthStatus, dict[str, Any]]:
    """Run one dependency check, converting any exception into a `down`.

    A check that raises must never turn into a 500 from the readiness endpoint: the
    orchestrator needs a verdict, and "we could not tell" is exactly as down as "it is down".
    """
    from app.ports.health import ComponentHealth

    try:
        outcome = await check()
    except Exception as exc:
        _LOG.warning("readiness_check_raised", component=name, error_type=type(exc).__name__)
        return name, HealthStatus.DOWN, {"reason": "check raised"}
    if isinstance(outcome, ComponentHealth):
        return outcome.name, outcome.status, outcome.details
    if isinstance(outcome, tuple) and len(outcome) == 2:
        status, details = outcome
        return name, status, dict(details or {})
    return name, HealthStatus.UNKNOWN, {"reason": "check returned an unexpected shape"}


def _down_names(components: dict[str, Any]) -> list[str]:
    return [name for name, body in components.items() if body["status"] == HealthStatus.DOWN.value]


_SEVERITY = {
    HealthStatus.OK: 0,
    HealthStatus.DEGRADED: 1,
    HealthStatus.UNKNOWN: 2,
    HealthStatus.DOWN: 3,
}
