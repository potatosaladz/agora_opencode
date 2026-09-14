"""Live PostgreSQL Phase 5 retrieval baseline and exit-gate proof (FR-402, FR-404)."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.adapters.pgvector.vector_store import PostgresKnowledgeVectorIndex
from app.adapters.retrieval.postgres import PostgresCandidateSearch
from app.application.retrieval import HybridRetriever, NoopReranker
from app.application.retrieval_baseline import BaselineCorpus, evaluate_baseline
from app.common.errors import RagFailed
from app.db.retrieval import PostgresRetrievalAudit
from app.domain.knowledge import KnowledgeEmbedding, NamespaceSubjectKind
from app.domain.retrieval import PrincipalClass, RetrievalRequest, RetrievalSubject
from app.ports.errors import PermanentPortError
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL not configured"),
]
_FIXTURE = Path(__file__).parents[1] / "fixtures" / "retrieval_baseline_v1.json"
_NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
_DIMENSIONS = 1536


def _vector(axis: int) -> list[float]:
    value = [0.0] * _DIMENSIONS
    value[axis] = 1.0
    return value


async def _seed_corpus(
    engine: AsyncEngine,
    corpus: BaselineCorpus,
    workspace: UUID,
    user: UUID,
    allowed_namespace: UUID,
    denied_namespace: UUID,
) -> tuple[UUID, ...]:
    denied_chunks = tuple(
        chunk.id
        for source in corpus.sources
        if source.namespace == "UNAUTHORIZED"
        for chunk in source.chunks
    )
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO workspaces (id, slug, name) VALUES (:id, :slug, 'T5-09')"),
            {"id": workspace, "slug": f"t509-{workspace.hex}"},
        )
        await connection.execute(
            text(
                "INSERT INTO users (id, oidc_issuer, oidc_subject, display_name) "
                "VALUES (:id, 'fixture', :subject, 'Baseline Reviewer')"
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
        for namespace, name in (
            (allowed_namespace, "mechanics-synthetic-v1"),
            (denied_namespace, "mechanics-unauthorized-v1"),
        ):
            await connection.execute(
                text(
                    "INSERT INTO knowledge_namespaces (id, workspace_id, tier, name) "
                    "VALUES (:id, :workspace, 'WORKSPACE', :name)"
                ),
                {"id": namespace, "workspace": workspace, "name": name},
            )
        await connection.execute(
            text(
                "INSERT INTO knowledge_namespace_grants "
                "(id, workspace_id, namespace_id, subject_kind, subject_id, "
                "capability, valid_from) "
                "VALUES (:id, :workspace, :namespace, 'WORKSPACE', :workspace, 'READ', :now)"
            ),
            {
                "id": uuid4(),
                "workspace": workspace,
                "namespace": allowed_namespace,
                "now": _NOW,
            },
        )
        for source in corpus.sources:
            namespace = allowed_namespace if source.namespace == "AUTHORIZED" else denied_namespace
            await connection.execute(
                text(
                    "INSERT INTO sources (id, workspace_id, namespace_id, title, citation, "
                    "object_ref, content_hash, media_type, size_bytes, trust_level, status, "
                    "retracted_at, retraction_reason) VALUES "
                    "(:id, :workspace, :namespace, :title, :title, :object_ref, :hash, "
                    "'text/plain', 128, 'SYNTHETIC', :status, :retracted_at, :reason)"
                ),
                {
                    "id": source.id,
                    "workspace": workspace,
                    "namespace": namespace,
                    "title": source.title,
                    "object_ref": f"minio://sources/{source.content_hash}",
                    "hash": source.content_hash,
                    "status": source.status,
                    "retracted_at": _NOW if source.status == "RETRACTED" else None,
                    "reason": "superseded synthetic fixture"
                    if source.status == "RETRACTED"
                    else None,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO documents "
                    "(id, workspace_id, source_id, parser, parser_version, status) "
                    "VALUES (:id, :workspace, :source, 'fixture-json', :version, 'READY')"
                ),
                {
                    "id": source.document_id,
                    "workspace": workspace,
                    "source": source.id,
                    "version": corpus.parser_version,
                },
            )
            for ordinal, chunk in enumerate(source.chunks):
                await connection.execute(
                    text(
                        "INSERT INTO chunks "
                        "(id, workspace_id, document_id, ordinal, text, token_count, "
                        "locator, content_hash, chunker_version) VALUES "
                        "(:id, :workspace, :document, :ordinal, :text, 10, "
                        "CAST(:locator AS jsonb), "
                        ":hash, :chunker)"
                    ),
                    {
                        "id": chunk.id,
                        "workspace": workspace,
                        "document": source.document_id,
                        "ordinal": ordinal,
                        "text": chunk.text,
                        "locator": json.dumps(
                            {
                                "section": source.title,
                                "char_start": 0,
                                "char_end": len(chunk.text),
                            }
                        ),
                        "hash": chunk.content_hash,
                        "chunker": corpus.chunker_version,
                    },
                )

    index = PostgresKnowledgeVectorIndex(engine, workspace)
    embeddings = [
        KnowledgeEmbedding(
            namespace_id=(
                allowed_namespace if source.namespace == "AUTHORIZED" else denied_namespace
            ),
            chunk_id=chunk.id,
            document_id=source.document_id,
            source_id=source.id,
            content_hash=chunk.content_hash,
            embedding_model=corpus.embedding_model,
            embedding_version=corpus.embedding_version,
            vector=_vector(chunk.vector_axis),
        )
        for source in corpus.sources
        for chunk in source.chunks
    ]
    await index.upsert(embeddings)
    return denied_chunks


@req("FR-402", "FR-404", "FR-409")
async def test_fr402_fr404_phase5_baseline_resolves_digests_and_audits_isolation() -> None:
    assert _DATABASE_URL is not None
    corpus = BaselineCorpus.model_validate_json(_FIXTURE.read_text(encoding="utf-8"))
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "20260906_0016")
    await asyncio.to_thread(command.upgrade, config, "head")

    workspace, user, allowed_namespace, denied_namespace = (uuid4() for _ in range(4))
    denied_chunks = await _seed_corpus(
        engine, corpus, workspace, user, allowed_namespace, denied_namespace
    )
    subjects = (
        RetrievalSubject(kind=NamespaceSubjectKind.WORKSPACE, id=workspace),
        RetrievalSubject(kind=NamespaceSubjectKind.USER, id=user),
    )
    retriever = HybridRetriever(
        PostgresCandidateSearch(engine, workspace),
        NoopReranker(),
        PostgresRetrievalAudit(engine, workspace),
    )
    retrieved: dict[str, tuple[UUID, ...]] = {}
    result_attempts: list[UUID] = []
    for axis, query in enumerate(corpus.queries):
        attempt_id = uuid4()
        result_attempts.append(attempt_id)
        result = await retriever.retrieve(
            RetrievalRequest(
                attempt_id=attempt_id,
                trace_id=uuid4(),
                workspace_id=workspace,
                principal_class=PrincipalClass.HUMAN,
                principal_id=user,
                namespace_ids=(allowed_namespace, denied_namespace),
                subjects=subjects,
                query=query.text,
                query_vector=_vector(axis),
                embedding_model=corpus.embedding_model,
                embedding_version=corpus.embedding_version,
                index_version=corpus.index_version,
                requested_at=_NOW,
                final_k=corpus.final_k,
                lexical_min_score=0.2,
                vector_min_score=0.99,
            )
        )
        assert result.searched_namespace_ids == (allowed_namespace,)
        assert not ({chunk.chunk_id for chunk in result.chunks} & set(denied_chunks))
        retrieved[query.id] = tuple(chunk.chunk_id for chunk in result.chunks)
        assert retrieved[query.id] == query.expected_retrieved_chunk_ids
        async with engine.begin() as connection:
            resolved = (
                await connection.execute(
                    text(
                        "SELECT c.id, c.content_hash, s.content_hash AS source_hash "
                        "FROM chunks c JOIN documents d ON d.workspace_id = c.workspace_id "
                        "AND d.id = c.document_id JOIN sources s "
                        "ON s.workspace_id = d.workspace_id "
                        "AND s.id = d.source_id WHERE c.id = ANY(CAST(:ids AS uuid[]))"
                    ),
                    {"ids": list(retrieved[query.id])},
                )
            ).mappings()
            resolved_rows = list(resolved)
        assert len(resolved_rows) == len(result.chunks)
        assert all(row["content_hash"].startswith("sha256:") for row in resolved_rows)
        assert all(row["source_hash"].startswith("sha256:") for row in resolved_rows)

    metrics = evaluate_baseline(corpus, retrieved)
    assert metrics.recall_proxy == 1.0
    assert metrics.precision_at_k >= 0.5

    denied_attempt = uuid4()
    with pytest.raises(PermanentPortError, match="no requested namespace"):
        await retriever.retrieve(
            RetrievalRequest(
                attempt_id=denied_attempt,
                trace_id=uuid4(),
                workspace_id=workspace,
                principal_class=PrincipalClass.HUMAN,
                principal_id=user,
                namespace_ids=(denied_namespace,),
                subjects=subjects,
                query=corpus.queries[0].text,
                query_vector=_vector(0),
                embedding_model=corpus.embedding_model,
                embedding_version=corpus.embedding_version,
                index_version=corpus.index_version,
                requested_at=_NOW,
                final_k=corpus.final_k,
            )
        )
    async with engine.begin() as connection:
        audits = (
            await connection.execute(
                text(
                    "SELECT attempt_id, outcome, requested_namespace_ids, searched_namespace_ids, "
                    "result_chunk_ids, result_content_hashes FROM retrieval_attempts "
                    "WHERE attempt_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": [*result_attempts, denied_attempt]},
            )
        ).mappings()
        audit_by_id = {row["attempt_id"]: row for row in audits}
    assert len(audit_by_id) == len(corpus.queries) + 1
    assert audit_by_id[denied_attempt]["outcome"] == "DENIED"
    assert audit_by_id[denied_attempt]["requested_namespace_ids"] == [denied_namespace]
    assert audit_by_id[denied_attempt]["searched_namespace_ids"] == []
    assert audit_by_id[denied_attempt]["result_chunk_ids"] == []
    assert audit_by_id[denied_attempt]["result_content_hashes"] == []

    failed_attempt = uuid4()
    with pytest.raises(RagFailed):
        await retriever.retrieve(
            RetrievalRequest(
                attempt_id=failed_attempt,
                trace_id=uuid4(),
                workspace_id=workspace,
                principal_class=PrincipalClass.HUMAN,
                principal_id=user,
                namespace_ids=(allowed_namespace,),
                subjects=subjects,
                query="expected synthetic phrase that is absent",
                query_vector=_vector(10),
                embedding_model=corpus.embedding_model,
                embedding_version=corpus.embedding_version,
                index_version=corpus.index_version,
                requested_at=_NOW,
                expected_match=True,
                final_k=corpus.final_k,
                lexical_min_score=0.99,
                vector_min_score=0.99,
            )
        )
    async with engine.begin() as connection:
        failed_audit = (
            (
                await connection.execute(
                    text(
                        "SELECT outcome, searched_namespace_ids, result_chunk_ids, warnings "
                        "FROM retrieval_attempts WHERE attempt_id = :id"
                    ),
                    {"id": failed_attempt},
                )
            )
            .mappings()
            .one()
        )
    assert failed_audit["outcome"] == "RAG_FAILED"
    assert failed_audit["searched_namespace_ids"] == [allowed_namespace]
    assert failed_audit["result_chunk_ids"] == []
    assert failed_audit["warnings"] == ["RAG_FAILED: expected match returned no candidates"]
    await asyncio.to_thread(command.check, config)
    await engine.dispose()
