"""PostgreSQL persistence for append-only retrieval attempt audits."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.retrieval import RetrievalAttemptRow
from app.domain.retrieval import RetrievalAttempt, RetrievalAudit
from app.ports.errors import PermanentPortError, TransientPortError

__all__ = ["PostgresRetrievalAudit"]

_PORT = "retrieval_audit"
_TRANSIENT_SQLSTATES = frozenset({"40001", "40P01", "55P03", "57014"})


class PostgresRetrievalAudit:
    def __init__(self, engine: AsyncEngine, workspace_id: UUID) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._workspace_id = workspace_id

    async def append(self, attempt: RetrievalAttempt) -> None:
        if attempt.workspace_id != self._workspace_id:
            raise PermanentPortError(
                "retrieval audit workspace does not match adapter scope", port=_PORT
            )
        values = attempt.model_dump(mode="python")
        values["principal_class"] = attempt.principal_class.value
        values["outcome"] = attempt.outcome.value
        values["degradation"] = attempt.degradation.value if attempt.degradation else None
        values["requested_namespace_ids"] = list(attempt.requested_namespace_ids)
        values["searched_namespace_ids"] = list(attempt.searched_namespace_ids)
        values["result_chunk_ids"] = list(attempt.result_chunk_ids)
        values["result_content_hashes"] = list(attempt.result_content_hashes)
        values["warnings"] = list(attempt.warnings)
        try:
            async with self._sessions.begin() as session:
                await session.execute(
                    text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                    {"workspace_id": str(self._workspace_id)},
                )
                await session.execute(insert(RetrievalAttemptRow).values(**values))
        except DBAPIError as exc:
            error = (
                TransientPortError
                if exc.connection_invalidated
                or getattr(exc.orig, "sqlstate", None) in _TRANSIENT_SQLSTATES
                else PermanentPortError
            )
            raise error("PostgreSQL retrieval audit append failed", port=_PORT, cause=exc) from exc
        except SQLAlchemyError as exc:
            raise TransientPortError(
                "PostgreSQL retrieval audit append failed", port=_PORT, cause=exc
            ) from exc


_RETRIEVAL_AUDIT_PORT: type[RetrievalAudit] = PostgresRetrievalAudit
