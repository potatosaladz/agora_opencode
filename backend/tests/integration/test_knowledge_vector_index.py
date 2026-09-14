"""Live PostgreSQL proof for UUID-backed knowledge vector indexing."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.adapters.pgvector.vector_store import PostgresKnowledgeVectorIndex, PostgresVectorStore
from app.adapters.retrieval.postgres import PostgresCandidateSearch
from app.application.retrieval import HybridRetriever, NoopReranker
from app.db.retrieval import PostgresRetrievalAudit
from app.domain.knowledge import KnowledgeEmbedding, NamespaceSubjectKind
from app.domain.retrieval import PrincipalClass, RetrievalRequest, RetrievalSubject
from app.ports.data import VectorItem
from app.ports.errors import PermanentPortError
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL not configured"),
]
_DIMENSIONS = 1536
_HASH_A = "sha256:" + "a" * 64
_HASH_B = "sha256:" + "b" * 64
_NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


def _vector(axis: int = 0) -> list[float]:
    value = [0.0] * _DIMENSIONS
    value[axis] = 1.0
    return value


def _embedding(
    namespace_id: UUID,
    chunk_id: UUID,
    document_id: UUID,
    source_id: UUID,
    content_hash: str,
) -> KnowledgeEmbedding:
    return KnowledgeEmbedding(
        namespace_id=namespace_id,
        chunk_id=chunk_id,
        document_id=document_id,
        source_id=source_id,
        content_hash=content_hash,
        embedding_model="fixture-embed",
        embedding_version="1",
        vector=_vector(),
    )


async def _insert_chain(
    engine: AsyncEngine,
    *,
    workspace_id: UUID,
    namespace_id: UUID,
    source_id: UUID,
    document_id: UUID,
    chunks: tuple[tuple[UUID, str], ...],
    texts: dict[UUID, str] | None = None,
    acls: dict[UUID, tuple[UUID, ...]] | None = None,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO workspaces (id, slug, name) VALUES (:id, :slug, :slug) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": workspace_id, "slug": f"vector-{workspace_id}"},
        )
        await connection.execute(
            text(
                "INSERT INTO knowledge_namespaces (id, workspace_id, tier, name) "
                "VALUES (:id, :workspace_id, 'WORKSPACE', :name)"
            ),
            {"id": namespace_id, "workspace_id": workspace_id, "name": str(namespace_id)},
        )
        await connection.execute(
            text(
                "INSERT INTO sources (id, workspace_id, namespace_id, title, citation, "
                "object_ref, content_hash, media_type, size_bytes) VALUES "
                "(:id, :workspace_id, :namespace_id, 'Fixture', 'Fixture', 'minio://fixture', "
                ":content_hash, 'text/plain', 7)"
            ),
            {
                "id": source_id,
                "workspace_id": workspace_id,
                "namespace_id": namespace_id,
                "content_hash": _HASH_A,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO documents (id, workspace_id, source_id, parser, parser_version, "
                "status) VALUES (:id, :workspace_id, :source_id, 'txt', '1', 'READY')"
            ),
            {"id": document_id, "workspace_id": workspace_id, "source_id": source_id},
        )
        for ordinal, (chunk_id, content_hash) in enumerate(chunks):
            await connection.execute(
                text(
                    "INSERT INTO chunks (id, workspace_id, document_id, ordinal, text, "
                    "token_count, locator, content_hash, chunker_version, acl) VALUES "
                    "(:id, :workspace_id, :document_id, :ordinal, :text, 1, "
                    "CAST(:locator AS jsonb), :content_hash, "
                    "'agora-whitespace-v1', CAST(:acl AS uuid[]))"
                ),
                {
                    "id": chunk_id,
                    "workspace_id": workspace_id,
                    "document_id": document_id,
                    "ordinal": ordinal,
                    "text": (texts or {}).get(chunk_id, "fixture"),
                    "locator": '{"char_start":0,"char_end":7}',
                    "content_hash": content_hash,
                    "acl": list((acls or {}).get(chunk_id, ())),
                },
            )


@req("FR-405", "FR-407", "NFR-010")
async def test_uuid_knowledge_vectors_reject_stale_data_and_enforce_rls() -> None:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(command.upgrade, config, "head")

    workspace_a, namespace_a, source_a, document_a = [uuid4() for _ in range(4)]
    chunk_a = UUID("00000000-0000-0000-0000-000000000001")
    chunk_b = UUID("00000000-0000-0000-0000-000000000002")
    await _insert_chain(
        engine,
        workspace_id=workspace_a,
        namespace_id=namespace_a,
        source_id=source_a,
        document_id=document_a,
        chunks=((chunk_b, _HASH_B), (chunk_a, _HASH_A)),
    )
    workspace_b, namespace_b, source_b, document_b, chunk_c = [uuid4() for _ in range(5)]
    await _insert_chain(
        engine,
        workspace_id=workspace_b,
        namespace_id=namespace_b,
        source_id=source_b,
        document_id=document_b,
        chunks=((chunk_c, _HASH_A),),
    )

    namespace_d, source_d, document_d, chunk_d = [uuid4() for _ in range(4)]
    await _insert_chain(
        engine,
        workspace_id=workspace_a,
        namespace_id=namespace_d,
        source_id=source_d,
        document_id=document_d,
        chunks=((chunk_d, _HASH_A),),
    )
    namespace_e, source_e, document_e, chunk_e = [uuid4() for _ in range(4)]
    await _insert_chain(
        engine,
        workspace_id=workspace_a,
        namespace_id=namespace_e,
        source_id=source_e,
        document_id=document_e,
        chunks=((chunk_e, _HASH_A),),
    )

    async with engine.begin() as connection:
        await connection.execute(text("DROP ROLE IF EXISTS agora_t504_app"))
        await connection.execute(text("CREATE ROLE agora_t504_app NOLOGIN"))
        await connection.execute(text("GRANT USAGE ON SCHEMA public TO agora_t504_app"))
        await connection.execute(
            text(
                "GRANT SELECT ON knowledge_namespaces, sources, documents, chunks TO agora_t504_app"
            )
        )
        await connection.execute(
            text("GRANT SELECT, INSERT, UPDATE, DELETE ON vector_items TO agora_t504_app")
        )

    runtime_engine = create_async_engine(
        _DATABASE_URL,
        connect_args={"server_settings": {"role": "agora_t504_app"}},
    )

    index_a = PostgresKnowledgeVectorIndex(runtime_engine, workspace_a)
    index_b = PostgresKnowledgeVectorIndex(runtime_engine, workspace_b)
    legacy_store = PostgresVectorStore(runtime_engine, workspace_a)
    preexisting_legacy_item = VectorItem(
        chunk_id=str(chunk_e),
        document_id="legacy-document",
        source_id="legacy-source",
        content_hash=_HASH_A,
        vector=_vector(),
    )
    await legacy_store.upsert(str(namespace_e), [preexisting_legacy_item])
    with pytest.raises(PermanentPortError, match="authoritative chunk provenance"):
        await index_a.upsert([_embedding(namespace_e, chunk_e, document_e, source_e, _HASH_A)])
    assert [
        hit.chunk_id
        for hit in await legacy_store.query(
            str(namespace_e), _vector(), k=10, filters={}, min_score=0.0
        )
    ] == [str(chunk_e)]
    with pytest.raises(PermanentPortError, match="authoritative chunk provenance"):
        await index_a.upsert([_embedding(namespace_a, chunk_a, document_a, source_a, _HASH_B)])
    with pytest.raises(PermanentPortError, match="authoritative chunk provenance"):
        await index_a.upsert([_embedding(namespace_a, chunk_a, document_a, source_b, _HASH_A)])

    await index_a.upsert(
        [
            _embedding(namespace_a, chunk_b, document_a, source_a, _HASH_B),
            _embedding(namespace_a, chunk_a, document_a, source_a, _HASH_A),
        ]
    )
    with pytest.raises(PermanentPortError, match="model/version"):
        await index_a.upsert(
            [
                _embedding(namespace_a, chunk_a, document_a, source_a, _HASH_A).model_copy(
                    update={"embedding_version": "2"}
                )
            ]
        )
    await index_b.upsert([_embedding(namespace_b, chunk_c, document_b, source_b, _HASH_A)])
    await asyncio.wait_for(
        asyncio.gather(
            index_a.upsert(
                [
                    _embedding(namespace_a, chunk_a, document_a, source_a, _HASH_A),
                    _embedding(namespace_d, chunk_d, document_d, source_d, _HASH_A),
                ]
            ),
            index_a.upsert(
                [
                    _embedding(namespace_d, chunk_d, document_d, source_d, _HASH_A),
                    _embedding(namespace_a, chunk_a, document_a, source_a, _HASH_A),
                ]
            ),
        ),
        timeout=10,
    )
    hits = await index_a.query(
        namespace_a,
        _vector(),
        embedding_model="fixture-embed",
        embedding_version="1",
        k=10,
        min_score=0.0,
    )
    assert [hit.chunk_id for hit in hits] == [chunk_a, chunk_b]
    assert all(hit.document_id == document_a and hit.source_id == source_a for hit in hits)
    assert (
        await index_a.query(
            namespace_b,
            _vector(),
            embedding_model="fixture-embed",
            embedding_version="1",
            k=10,
            min_score=0.0,
        )
        == []
    )
    with pytest.raises(PermanentPortError, match="model/version"):
        await index_a.query(
            namespace_a,
            _vector(),
            embedding_model="fixture-embed",
            embedding_version="2",
            k=10,
            min_score=0.0,
        )

    async with engine.begin() as connection:
        index_definition = cast(
            str,
            await connection.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_vector_items_embedding_cosine'"
                )
            ),
        )
        assert "ivfflat" in index_definition
        assert "vector_cosine_ops" in index_definition
        await connection.execute(
            text("UPDATE vector_items SET content_hash = :stale WHERE chunk_uuid = :chunk_id"),
            {"stale": _HASH_B, "chunk_id": chunk_a},
        )
    fresh_hits = await index_a.query(
        namespace_a,
        _vector(),
        embedding_model="fixture-embed",
        embedding_version="1",
        k=10,
        min_score=0.0,
    )
    assert [hit.chunk_id for hit in fresh_hits] == [chunk_b]

    colliding_item = VectorItem(
        chunk_id=str(chunk_b),
        document_id="legacy-document",
        source_id="legacy-source",
        content_hash=_HASH_A,
        vector=_vector(),
    )
    with pytest.raises(PermanentPortError, match="conflicts with UUID-backed"):
        await legacy_store.upsert(str(namespace_a), [colliding_item])
    assert (
        await legacy_store.query(str(namespace_a), _vector(), k=10, filters={}, min_score=0.0) == []
    )
    assert await legacy_store.delete_namespace(str(namespace_a)) == 0
    assert [
        hit.chunk_id
        for hit in await index_a.query(
            namespace_a,
            _vector(),
            embedding_model="fixture-embed",
            embedding_version="1",
            k=10,
            min_score=0.0,
        )
    ] == [chunk_b]

    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE sources SET status = 'PROCESSING' WHERE id = :source_id"),
            {"source_id": source_a},
        )
    assert (
        await index_a.query(
            namespace_a,
            _vector(),
            embedding_model="fixture-embed",
            embedding_version="1",
            k=10,
            min_score=0.0,
        )
        == []
    )
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE sources SET status = 'FAILED' WHERE id = :source_id"),
            {"source_id": source_a},
        )
    assert (
        await index_a.query(
            namespace_a,
            _vector(),
            embedding_model="fixture-embed",
            embedding_version="1",
            k=10,
            min_score=0.0,
        )
        == []
    )
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE sources SET status = 'READY' WHERE id = :source_id"),
            {"source_id": source_a},
        )
        await connection.execute(
            text("UPDATE documents SET status = 'FAILED' WHERE id = :document_id"),
            {"document_id": document_a},
        )
    assert (
        await index_a.query(
            namespace_a,
            _vector(),
            embedding_model="fixture-embed",
            embedding_version="1",
            k=10,
            min_score=0.0,
        )
        == []
    )
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE documents SET status = 'READY' WHERE id = :document_id"),
            {"document_id": document_a},
        )

    with pytest.raises(PermanentPortError, match="authoritative chunk provenance"):
        await index_a.upsert([_embedding(namespace_b, chunk_c, document_b, source_b, _HASH_A)])
    assert await index_a.delete_namespace(namespace_b) == 0

    assert await index_a.delete_namespace(namespace_a) == 2
    assert await index_b.delete_namespace(namespace_b) == 1
    assert await index_a.delete_namespace(namespace_d) == 1
    assert await legacy_store.delete_namespace(str(namespace_e)) == 1
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE sources SET status = 'RETRACTED', retracted_at = now(), "
                "retraction_reason = 'fixture retraction' "
                "WHERE id = :source_id"
            ),
            {"source_id": source_a},
        )
    assert (
        await index_a.query(
            namespace_a,
            _vector(),
            embedding_model="fixture-embed",
            embedding_version="1",
            k=10,
            min_score=0.0,
        )
        == []
    )
    await asyncio.to_thread(command.check, config)
    await runtime_engine.dispose()
    await engine.dispose()


@req("FR-404", "FR-405", "NFR-010")
async def test_hybrid_retrieval_filters_grants_and_acl_before_scoring() -> None:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(command.upgrade, config, "head")

    workspace, user = uuid4(), uuid4()
    allowed_namespace, denied_namespace = uuid4(), uuid4()
    allowed_source, denied_source = uuid4(), uuid4()
    allowed_document, denied_document = uuid4(), uuid4()
    lexical_chunk = UUID("00000000-0000-0000-0000-000000000011")
    vector_chunk = UUID("00000000-0000-0000-0000-000000000012")
    acl_denied_chunk = UUID("00000000-0000-0000-0000-000000000013")
    namespace_denied_chunk = UUID("00000000-0000-0000-0000-000000000014")
    other_user = uuid4()
    await _insert_chain(
        engine,
        workspace_id=workspace,
        namespace_id=allowed_namespace,
        source_id=allowed_source,
        document_id=allowed_document,
        chunks=(
            (lexical_chunk, _HASH_A),
            (vector_chunk, _HASH_B),
            (acl_denied_chunk, "sha256:" + "c" * 64),
        ),
        texts={
            lexical_chunk: "Budget identifier ACME-2027",
            vector_chunk: "semantic paraphrase",
            acl_denied_chunk: "Budget identifier ACME-2027",
        },
        acls={acl_denied_chunk: (other_user,)},
    )
    await _insert_chain(
        engine,
        workspace_id=workspace,
        namespace_id=denied_namespace,
        source_id=denied_source,
        document_id=denied_document,
        chunks=((namespace_denied_chunk, "sha256:" + "d" * 64),),
        texts={namespace_denied_chunk: "Budget identifier ACME-2027"},
    )
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (id, oidc_issuer, oidc_subject, display_name) "
                "VALUES (:id, 'fixture', :subject, 'Fixture User')"
            ),
            {"id": user, "subject": str(user)},
        )
        await connection.execute(
            text(
                "INSERT INTO workspace_members (workspace_id, user_id, role) "
                "VALUES (:workspace, :user, 'RESEARCHER')"
            ),
            {"workspace": workspace, "user": user},
        )
        await connection.execute(
            text(
                "INSERT INTO knowledge_namespace_grants "
                "(id, workspace_id, namespace_id, subject_kind, subject_id, capability, "
                "valid_from) VALUES "
                "(:id, :workspace, :namespace, 'WORKSPACE', :workspace, 'READ', :valid_from)"
            ),
            {
                "id": uuid4(),
                "workspace": workspace,
                "namespace": allowed_namespace,
                "valid_from": _NOW,
            },
        )
        index_definition = cast(
            str,
            await connection.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_chunks_search_vector_gin'"
                )
            ),
        )
        assert "USING gin" in index_definition

    index = PostgresKnowledgeVectorIndex(engine, workspace)
    await index.upsert(
        [
            _embedding(allowed_namespace, vector_chunk, allowed_document, allowed_source, _HASH_B),
            _embedding(
                allowed_namespace,
                acl_denied_chunk,
                allowed_document,
                allowed_source,
                "sha256:" + "c" * 64,
            ),
            _embedding(
                denied_namespace,
                namespace_denied_chunk,
                denied_document,
                denied_source,
                "sha256:" + "d" * 64,
            ),
        ]
    )
    request = RetrievalRequest(
        attempt_id=uuid4(),
        trace_id=uuid4(),
        workspace_id=workspace,
        principal_class=PrincipalClass.HUMAN,
        principal_id=user,
        namespace_ids=(allowed_namespace, denied_namespace),
        subjects=(
            RetrievalSubject(kind=NamespaceSubjectKind.WORKSPACE, id=workspace),
            RetrievalSubject(kind=NamespaceSubjectKind.USER, id=user),
        ),
        query="ACME-2027",
        query_vector=_vector(),
        embedding_model="fixture-embed",
        embedding_version="1",
        index_version="fixture-index-1",
        requested_at=_NOW,
        final_k=5,
        lexical_min_score=0.05,
        vector_min_score=0.9,
    )
    retriever = HybridRetriever(
        PostgresCandidateSearch(engine, workspace),
        NoopReranker(),
        PostgresRetrievalAudit(engine, workspace),
    )
    first = await retriever.retrieve(request)
    second_request = request.model_copy(update={"attempt_id": uuid4()})
    second = await retriever.retrieve(second_request)

    assert first == second
    assert first.requested_namespace_ids == (allowed_namespace, denied_namespace)
    assert first.searched_namespace_ids == (allowed_namespace,)
    assert first.lexical_count == 1
    assert first.vector_count == 1
    assert [chunk.chunk_id for chunk in first.chunks] == [lexical_chunk, vector_chunk]
    assert first.chunks[0].lexical_score is not None
    assert first.chunks[0].vector_score is None
    assert first.chunks[1].lexical_score is None
    assert first.chunks[1].vector_score == pytest.approx(1.0)
    assert acl_denied_chunk not in {chunk.chunk_id for chunk in first.chunks}
    assert namespace_denied_chunk not in {chunk.chunk_id for chunk in first.chunks}
    async with engine.begin() as connection:
        audits = (
            (
                await connection.execute(
                    text(
                        "SELECT principal_class, principal_id, requested_namespace_ids, "
                        "searched_namespace_ids, result_chunk_ids, result_content_hashes, outcome "
                        "FROM retrieval_attempts ORDER BY created_at"
                    )
                )
            )
            .mappings()
            .all()
        )
    assert len(audits) == 2
    assert all(row["principal_class"] == "HUMAN" for row in audits)
    assert all(row["principal_id"] == user for row in audits)
    assert all(row["outcome"] == "ALLOWED" for row in audits)
    assert audits[0]["requested_namespace_ids"] == [allowed_namespace, denied_namespace]
    assert audits[0]["searched_namespace_ids"] == [allowed_namespace]
    assert audits[0]["result_chunk_ids"] == [lexical_chunk, vector_chunk]
    assert audits[0]["result_content_hashes"] == [_HASH_A, _HASH_B]
    await engine.dispose()
