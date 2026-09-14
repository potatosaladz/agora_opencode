"""PostgreSQL/pgvector implementation of the `VectorStore` port."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    String,
    Table,
    Text,
    delete,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.adapters.pgvector.types import Vector
from app.domain.knowledge import (
    KnowledgeEmbedding,
    KnowledgeVectorHit,
    KnowledgeVectorIndex,
)
from app.ports.data import VectorHit, VectorItem, VectorStore
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.health import HealthStatus

__all__ = ["PostgresKnowledgeVectorIndex", "PostgresVectorStore", "register_pgvector_metadata"]

_PORT = "vector_store"
_DIMENSIONS = 1536
_TRANSIENT_SQLSTATES = frozenset({"40001", "40P01", "55P03", "57014"})


def _vector_items_table(metadata: MetaData, *, include_workspace_fk: bool) -> Table:
    workspace_constraints = (
        (ForeignKey("workspaces.id", ondelete="RESTRICT"),) if include_workspace_fk else ()
    )
    table = Table(
        "vector_items",
        metadata,
        Column("workspace_id", PGUUID(as_uuid=True), *workspace_constraints, primary_key=True),
        Column("namespace", String(255), primary_key=True),
        Column("chunk_id", String(255), primary_key=True),
        Column("document_id", String(255), nullable=False),
        Column("source_id", String(255), nullable=False),
        Column("content_hash", Text, nullable=False),
        Column("embedding", Vector(_DIMENSIONS), nullable=False),
        Column("metadata", JSONB, nullable=False),
        Column("namespace_id", PGUUID(as_uuid=True)),
        Column("chunk_uuid", PGUUID(as_uuid=True)),
        Column("document_uuid", PGUUID(as_uuid=True)),
        Column("source_uuid", PGUUID(as_uuid=True)),
        Column("embedding_model", Text),
        Column("embedding_version", Text),
        Column("created_at", DateTime(timezone=True), server_default=text("now()")),
        CheckConstraint(
            "(namespace_id IS NULL AND chunk_uuid IS NULL AND document_uuid IS NULL "
            "AND source_uuid IS NULL AND embedding_model IS NULL AND embedding_version IS NULL) OR "
            "(namespace_id IS NOT NULL AND chunk_uuid IS NOT NULL AND document_uuid IS NOT NULL "
            "AND source_uuid IS NOT NULL AND embedding_model IS NOT NULL "
            "AND length(btrim(embedding_model)) > 0 AND embedding_version IS NOT NULL "
            "AND length(btrim(embedding_version)) > 0)",
            name="knowledge_identity_complete",
        ),
        *(
            (
                ForeignKeyConstraint(
                    ["workspace_id", "namespace_id"],
                    ["knowledge_namespaces.workspace_id", "knowledge_namespaces.id"],
                    name="fk_vector_items_namespace_workspace",
                    ondelete="CASCADE",
                ),
                ForeignKeyConstraint(
                    ["workspace_id", "chunk_uuid", "document_uuid"],
                    ["chunks.workspace_id", "chunks.id", "chunks.document_id"],
                    name="fk_vector_items_chunk_document",
                    ondelete="CASCADE",
                ),
                ForeignKeyConstraint(
                    ["workspace_id", "document_uuid", "source_uuid"],
                    ["documents.workspace_id", "documents.id", "documents.source_id"],
                    name="fk_vector_items_document_source",
                    ondelete="CASCADE",
                ),
                ForeignKeyConstraint(
                    ["workspace_id", "source_uuid", "namespace_id"],
                    ["sources.workspace_id", "sources.id", "sources.namespace_id"],
                    name="fk_vector_items_source_namespace",
                    ondelete="CASCADE",
                ),
            )
            if include_workspace_fk
            else ()
        ),
    )
    Index("ix_vector_items_workspace_namespace", table.c.workspace_id, table.c.namespace)
    Index(
        "ix_vector_items_knowledge_scope",
        table.c.workspace_id,
        table.c.namespace_id,
        table.c.embedding_model,
        table.c.embedding_version,
    )
    Index(
        "ix_vector_items_embedding_cosine",
        table.c.embedding,
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 10},
    )
    return table


def register_pgvector_metadata(metadata: MetaData) -> Table:
    """Register adapter-owned pgvector schema for Alembic drift detection."""
    existing = metadata.tables.get("vector_items")
    if existing is None:
        existing = _vector_items_table(metadata, include_workspace_fk=True)
    return existing


_TABLE = _vector_items_table(MetaData(), include_workspace_fk=False)


class PostgresKnowledgeVectorIndex:
    """UUID-backed derived index that validates every write against provenance authority."""

    def __init__(self, engine: AsyncEngine, workspace_id: UUID) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._workspace_id = workspace_id

    async def upsert(self, items: Sequence[KnowledgeEmbedding]) -> None:
        if not items:
            return
        for item in items:
            PostgresVectorStore._require_dimensions(item.vector, subject=f"chunk {item.chunk_id!s}")
        try:
            async with self._sessions.begin() as session:
                await self._scope(session)
                namespace_ids = sorted({item.namespace_id for item in items})
                for namespace_id in namespace_ids:
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                        {
                            "identity": (
                                f"knowledge-vector:{self._workspace_id!s}:{namespace_id!s}"
                            ),
                        },
                    )
                for item in items:
                    indexed_identity = await session.execute(
                        select(_TABLE.c.embedding_model, _TABLE.c.embedding_version)
                        .where(
                            _TABLE.c.workspace_id == self._workspace_id,
                            _TABLE.c.namespace_id == item.namespace_id,
                        )
                        .distinct()
                    )
                    _require_index_identity(
                        set(indexed_identity.tuples()),
                        item.embedding_model,
                        item.embedding_version,
                    )
                    result = await session.execute(
                        text(
                            """
                            INSERT INTO vector_items
                              (workspace_id, namespace, chunk_id, document_id, source_id,
                               content_hash, embedding, metadata, namespace_id, chunk_uuid,
                               document_uuid, source_uuid, embedding_model, embedding_version)
                            SELECT c.workspace_id, s.namespace_id::text, c.id::text, d.id::text,
                                   s.id::text, c.content_hash, CAST(:embedding AS vector),
                                   '{}'::jsonb, s.namespace_id, c.id, d.id, s.id, :model, :version
                            FROM chunks c
                            JOIN documents d ON d.workspace_id = c.workspace_id
                                             AND d.id = c.document_id
                            JOIN sources s ON s.workspace_id = d.workspace_id
                                          AND s.id = d.source_id
                            WHERE c.workspace_id = :workspace_id AND c.id = :chunk_id
                              AND d.id = :document_id AND s.id = :source_id
                              AND s.namespace_id = :namespace_id
                              AND c.content_hash = :content_hash
                            ON CONFLICT (workspace_id, namespace, chunk_id)
                            DO UPDATE SET document_id = EXCLUDED.document_id,
                                          source_id = EXCLUDED.source_id,
                                          content_hash = EXCLUDED.content_hash,
                                          embedding = EXCLUDED.embedding,
                                          namespace_id = EXCLUDED.namespace_id,
                                          chunk_uuid = EXCLUDED.chunk_uuid,
                                          document_uuid = EXCLUDED.document_uuid,
                                          source_uuid = EXCLUDED.source_uuid,
                                          embedding_model = EXCLUDED.embedding_model,
                                          embedding_version = EXCLUDED.embedding_version,
                                          created_at = now()
                            WHERE vector_items.namespace_id IS NOT NULL
                            RETURNING chunk_uuid
                            """
                        ),
                        {
                            "workspace_id": self._workspace_id,
                            "namespace_id": item.namespace_id,
                            "chunk_id": item.chunk_id,
                            "document_id": item.document_id,
                            "source_id": item.source_id,
                            "content_hash": item.content_hash,
                            "model": item.embedding_model,
                            "version": item.embedding_version,
                            "embedding": str(list(item.vector)),
                        },
                    )
                    _require_authoritative_embedding(result.scalar_one_or_none())
        except PermanentPortError:
            raise
        except IntegrityError as exc:
            raise PermanentPortError(
                "PostgreSQL rejected knowledge embedding", port=_PORT, cause=exc
            ) from exc
        except DBAPIError as exc:
            error = TransientPortError if _is_transient_database_error(exc) else PermanentPortError
            raise error(
                "PostgreSQL knowledge vector operation failed", port=_PORT, cause=exc
            ) from exc
        except SQLAlchemyError as exc:
            raise TransientPortError(
                "PostgreSQL knowledge vector operation failed", port=_PORT, cause=exc
            ) from exc

    async def query(
        self,
        namespace_id: UUID,
        vector: Sequence[float],
        *,
        embedding_model: str,
        embedding_version: str,
        k: int,
        min_score: float,
    ) -> Sequence[KnowledgeVectorHit]:
        PostgresVectorStore._require_dimensions(vector, subject="query vector")
        if not embedding_model.strip() or not embedding_version.strip():
            raise PermanentPortError("embedding model and version are required", port=_PORT)
        if k <= 0:
            raise PermanentPortError(f"k must be positive, got {k}", port=_PORT)
        sql = text(
            """
            SELECT e.namespace_id, e.chunk_uuid AS chunk_id,
                   e.document_uuid AS document_id, e.source_uuid AS source_id,
                   e.content_hash, e.embedding_model, e.embedding_version,
                   c.chunker_version, c.locator,
                   1 - (e.embedding <=> CAST(:embedding AS vector)) AS score
            FROM vector_items e
            JOIN chunks c ON c.workspace_id = e.workspace_id AND c.id = e.chunk_uuid
                         AND c.document_id = e.document_uuid
            JOIN documents d ON d.workspace_id = e.workspace_id AND d.id = e.document_uuid
                            AND d.source_id = e.source_uuid
            JOIN sources s ON s.workspace_id = e.workspace_id AND s.id = e.source_uuid
                          AND s.namespace_id = e.namespace_id
            WHERE e.workspace_id = :workspace_id AND e.namespace_id = :namespace_id
              AND e.embedding_model = :model AND e.embedding_version = :version
              AND e.content_hash = c.content_hash
              AND s.status = 'READY' AND d.status = 'READY'
              AND 1 - (e.embedding <=> CAST(:embedding AS vector)) >= :min_score
            ORDER BY e.embedding <=> CAST(:embedding AS vector), e.chunk_uuid
            LIMIT :k
            """
        )
        try:
            async with self._sessions.begin() as session:
                await self._scope(session)
                await session.execute(text("SET LOCAL ivfflat.probes = 10"))
                indexed_identity = await session.execute(
                    select(_TABLE.c.embedding_model, _TABLE.c.embedding_version)
                    .where(
                        _TABLE.c.workspace_id == self._workspace_id,
                        _TABLE.c.namespace_id == namespace_id,
                    )
                    .distinct()
                )
                identities = set(indexed_identity.tuples())
                _require_index_identity(identities, embedding_model, embedding_version)
                rows = (
                    await session.execute(
                        sql,
                        {
                            "workspace_id": self._workspace_id,
                            "namespace_id": namespace_id,
                            "model": embedding_model,
                            "version": embedding_version,
                            "embedding": str(list(vector)),
                            "min_score": min_score,
                            "k": k,
                        },
                    )
                ).mappings()
                return [
                    KnowledgeVectorHit(
                        namespace_id=row["namespace_id"],
                        chunk_id=row["chunk_id"],
                        document_id=row["document_id"],
                        source_id=row["source_id"],
                        content_hash=row["content_hash"],
                        embedding_model=row["embedding_model"],
                        embedding_version=row["embedding_version"],
                        chunker_version=row["chunker_version"],
                        locator=row["locator"],
                        score=float(row["score"]),
                    )
                    for row in rows
                ]
        except PermanentPortError:
            raise
        except DBAPIError as exc:
            error = TransientPortError if _is_transient_database_error(exc) else PermanentPortError
            raise error("PostgreSQL knowledge vector query failed", port=_PORT, cause=exc) from exc
        except SQLAlchemyError as exc:
            raise TransientPortError(
                "PostgreSQL knowledge vector query failed", port=_PORT, cause=exc
            ) from exc

    async def delete_namespace(self, namespace_id: UUID) -> int:
        try:
            async with self._sessions.begin() as session:
                await self._scope(session)
                result = await session.execute(
                    delete(_TABLE).where(
                        _TABLE.c.workspace_id == self._workspace_id,
                        _TABLE.c.namespace_id == namespace_id,
                    )
                )
                return int(getattr(result, "rowcount", 0) or 0)
        except SQLAlchemyError as exc:
            raise TransientPortError(
                "PostgreSQL knowledge vector delete failed", port=_PORT, cause=exc
            ) from exc

    async def _scope(self, session: Any) -> None:
        await session.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(self._workspace_id)},
        )


def _require_authoritative_embedding(chunk_id: UUID | None) -> None:
    if chunk_id is None:
        raise PermanentPortError(
            "embedding does not match authoritative chunk provenance or content hash",
            port=_PORT,
        )


def _is_transient_database_error(exc: DBAPIError) -> bool:
    return exc.connection_invalidated or getattr(exc.orig, "sqlstate", None) in _TRANSIENT_SQLSTATES


def _require_all_legacy_rows_upserted(actual: int, expected: int) -> None:
    if actual != expected:
        raise PermanentPortError(
            "legacy vector key conflicts with UUID-backed knowledge row",
            port=_PORT,
        )


def _require_index_identity(
    identities: set[tuple[str | None, str | None]], model: str, version: str
) -> None:
    if identities and identities != {(model, version)}:
        raise PermanentPortError(
            "embedding model/version does not match the namespace index",
            port=_PORT,
        )


class PostgresVectorStore:
    """Cosine vector search scoped by both workspace RLS and explicit namespace."""

    def __init__(self, engine: AsyncEngine, workspace_id: UUID) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._workspace_id = workspace_id

    async def upsert(self, namespace: str, items: Sequence[VectorItem]) -> None:
        self._require_namespace(namespace)
        if not items:
            return
        for item in items:
            self._require_dimensions(item.vector, subject=f"chunk {item.chunk_id!r}")
        values = [
            {
                "workspace_id": self._workspace_id,
                "namespace": namespace,
                "chunk_id": item.chunk_id,
                "document_id": item.document_id,
                "source_id": item.source_id,
                "content_hash": item.content_hash,
                "embedding": list(item.vector),
                "metadata": dict(item.metadata),
            }
            for item in items
        ]
        insert_statement = insert(_TABLE).values(values)
        statement = insert_statement.on_conflict_do_update(
            index_elements=["workspace_id", "namespace", "chunk_id"],
            set_={
                "document_id": insert_statement.excluded.document_id,
                "source_id": insert_statement.excluded.source_id,
                "content_hash": insert_statement.excluded.content_hash,
                "embedding": insert_statement.excluded.embedding,
                "metadata": insert_statement.excluded.metadata,
                "namespace_id": None,
                "chunk_uuid": None,
                "document_uuid": None,
                "source_uuid": None,
                "embedding_model": None,
                "embedding_version": None,
            },
            where=_TABLE.c.namespace_id.is_(None),
        )
        returning_statement = statement.returning(_TABLE.c.chunk_id)
        try:
            async with self._sessions.begin() as session:
                await session.execute(
                    text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                    {"workspace_id": str(self._workspace_id)},
                )
                result = await session.execute(returning_statement)
                _require_all_legacy_rows_upserted(len(result.scalars().all()), len(items))
        except PermanentPortError:
            raise
        except IntegrityError as exc:
            raise PermanentPortError(
                f"PostgreSQL rejected vector data: {exc}", port=_PORT, cause=exc
            ) from exc
        except DBAPIError as exc:
            error = TransientPortError if _is_transient_database_error(exc) else PermanentPortError
            raise error(
                f"PostgreSQL vector operation failed: {exc}", port=_PORT, cause=exc
            ) from exc
        except SQLAlchemyError as exc:
            raise TransientPortError(
                f"PostgreSQL vector operation failed: {exc}", port=_PORT, cause=exc
            ) from exc

    async def query(
        self,
        namespace: str,
        vector: Sequence[float],
        *,
        k: int,
        filters: Mapping[str, Any],
        min_score: float,
    ) -> Sequence[VectorHit]:
        self._require_namespace(namespace)
        self._require_dimensions(vector, subject="query vector")
        if k <= 0:
            raise PermanentPortError(f"k must be positive, got {k}", port=_PORT)
        distance = _TABLE.c.embedding.cosine_distance(list(vector))
        statement = (
            select(
                _TABLE.c.chunk_id,
                _TABLE.c.document_id,
                _TABLE.c.source_id,
                _TABLE.c.content_hash,
                _TABLE.c.metadata,
                distance.label("distance"),
            )
            .where(_TABLE.c.workspace_id == self._workspace_id)
            .where(_TABLE.c.namespace == namespace)
            .where(_TABLE.c.namespace_id.is_(None))
            .where(1.0 - distance >= min_score)
            .order_by(distance, _TABLE.c.chunk_id)
            .limit(k)
        )
        if filters:
            statement = statement.where(_TABLE.c.metadata.contains(dict(filters)))
        rows = await self._execute(statement, probes=10)
        return [
            VectorHit(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                source_id=row.source_id,
                content_hash=row.content_hash,
                score=1.0 - float(row.distance),
                metadata=row.metadata,
            )
            for row in rows
        ]

    async def delete_namespace(self, namespace: str) -> int:
        self._require_namespace(namespace)
        result = await self._execute(
            delete(_TABLE).where(
                _TABLE.c.workspace_id == self._workspace_id,
                _TABLE.c.namespace == namespace,
                _TABLE.c.namespace_id.is_(None),
            )
        )
        return int(result.rowcount or 0)

    async def health(self) -> HealthStatus:
        try:
            result = await self._execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
            return HealthStatus.OK if result.scalar_one() else HealthStatus.DOWN
        except (PermanentPortError, TransientPortError):
            return HealthStatus.DOWN

    async def close(self) -> None:
        """No-op: the composition root owns the shared engine lifecycle."""

    async def _execute(self, statement: Any, *, probes: int | None = None) -> Any:
        try:
            async with self._sessions.begin() as session:
                await session.execute(
                    text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                    {"workspace_id": str(self._workspace_id)},
                )
                if probes is not None:
                    await session.execute(text(f"SET LOCAL ivfflat.probes = {probes}"))
                return await session.execute(statement)
        except IntegrityError as exc:
            raise PermanentPortError(
                f"PostgreSQL rejected vector data: {exc}", port=_PORT, cause=exc
            ) from exc
        except DBAPIError as exc:
            error = TransientPortError if _is_transient_database_error(exc) else PermanentPortError
            raise error(
                f"PostgreSQL vector operation failed: {exc}", port=_PORT, cause=exc
            ) from exc
        except SQLAlchemyError as exc:
            raise TransientPortError(
                f"PostgreSQL vector operation failed: {exc}", port=_PORT, cause=exc
            ) from exc

    @staticmethod
    def _require_namespace(namespace: str) -> None:
        if not namespace or not namespace.strip():
            raise PermanentPortError("an explicit namespace is required", port=_PORT)

    @staticmethod
    def _require_dimensions(vector: Sequence[float], *, subject: str) -> None:
        if len(vector) != _DIMENSIONS:
            raise PermanentPortError(
                f"{subject} must have {_DIMENSIONS} dimensions, got {len(vector)}", port=_PORT
            )


_VECTOR_STORE_PORT: type[VectorStore] = PostgresVectorStore
_KNOWLEDGE_VECTOR_INDEX_PORT: type[KnowledgeVectorIndex] = PostgresKnowledgeVectorIndex
