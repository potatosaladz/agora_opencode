"""HTTP layer: routes, middleware, problem+json. Transport only."""

from app.api.app import create_app

__all__ = ["create_app"]
