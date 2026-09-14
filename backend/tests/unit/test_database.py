"""Unit checks for database construction and tenant binding."""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import event, text

from app.config.settings import Settings
from app.db.session import Database, create_database
from tests.traceability import req


@req("FR-109", "NFR-010")
def test_create_database_uses_asyncpg_and_pool_settings() -> None:
    settings = Settings(
        environment="test",
        postgres_host="db.internal",
        postgres_db="testdb",
        postgres_user="app",
        postgres_password=SecretStr("encoded password"),
        db_pool_size=3,
        db_max_overflow=4,
    )

    database = create_database(settings)

    assert database.engine.url.drivername == "postgresql+asyncpg"
    assert database.engine.url.host == "db.internal"
    assert database.engine.url.database == "testdb"
    assert cast(Any, database.engine.pool).size() == 3


@req("FR-109", "NFR-010")
def test_baseline_enables_and_forces_rls_with_fail_closed_setting() -> None:
    migration = (
        Path(__file__).parents[2] / "alembic" / "versions" / "20260904_0001_baseline.py"
    ).read_text(encoding="utf-8")

    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "current_setting('app.workspace_id', true)" in migration
    assert "WITH CHECK" in migration


@req("FR-109", "NFR-010")
async def test_session_sets_workspace_transaction_locally() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine("sqlite+aiosqlite://")
    statements: list[tuple[str, str]] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute", retval=True)
    def replace_postgres_set_config(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        _executemany: bool,
    ) -> tuple[str, object]:
        if "set_config" in statement:
            statements.append((statement, str(parameters)))
            return "SELECT 1", ()
        return statement, parameters

    database = Database(engine)
    workspace_id = uuid4()
    async with database.session(workspace_id) as session:
        assert await session.scalar(text("SELECT 1")) == 1

    assert len(statements) == 1
    statement, parameters = statements[0]
    assert "app.workspace_id" in statement
    assert str(workspace_id) in parameters
    await database.close()
