"""Route modules, one per resource family, mounted by `app.api.app`."""

from app.api.routes.formalizations import router as formalizations_router
from app.api.routes.health import router as health_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.phase3 import router as phase3_router
from app.api.routes.realtime import router as realtime_router

__all__ = [
    "formalizations_router",
    "health_router",
    "metrics_router",
    "phase3_router",
    "realtime_router",
]
