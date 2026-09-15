"""Composition root for the deterministic external MCP fixture role."""

from __future__ import annotations

import asyncio

import uvicorn

from app.adapters.mcp.fixture import create_fixture_app
from app.config.settings import get_settings

__all__ = ["run_fixture"]


async def run_fixture() -> None:
    settings = get_settings()
    config = uvicorn.Config(
        create_fixture_app(),
        host=settings.host,
        port=settings.mcp_fixture_port,
        log_config=None,
        access_log=False,
    )
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(run_fixture())
