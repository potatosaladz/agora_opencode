"""Async PostgreSQL engine and tenant-scoped session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import Settings
from app.ports.health import HealthStatus

__all__ = ["Database", "create_database"]


class Database:
    """Own the engine and create transaction-local tenant sessions."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self, workspace_id: UUID) -> AsyncIterator[AsyncSession]:
        """Yield one transaction with the verified workspace bound for PostgreSQL RLS."""
        async with self.sessions.begin() as session:
            await session.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(workspace_id)},
            )
            yield session

    async def close(self) -> None:
        await self.engine.dispose()

    async def health(self) -> HealthStatus:
        """Check connectivity without leaking an exception or connection detail."""
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            return HealthStatus.DOWN
        return HealthStatus.OK


def create_database(settings: Settings) -> Database:
    """Build, but do not connect, the process-wide async database resources."""
    engine = create_async_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={
            "server_settings": {
                "statement_timeout": str(settings.db_statement_timeout_ms),
                "application_name": settings.service_name,
            }
        },
    )
    return Database(engine)
