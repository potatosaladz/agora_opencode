"""Hybrid retrieval domain, fusion, degradation, and SQL-boundary tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.application.retrieval import HybridRetriever, NoopReranker, reciprocal_rank_fusion
from app.common.errors import ErrorCode, RagFailed
from app.domain.knowledge import NamespaceSubjectKind
from app.domain.retrieval import (
    CandidateSearch,
    HybridCandidate,
    IndexMismatchError,
    PrincipalClass,
    Reranker,
    RetrievalAttempt,
    RetrievalAudit,
    RetrievalDegradation,
    RetrievalOutcome,
    RetrievalRequest,
    RetrievalSubject,
    RetrievedChunk,
)
from app.ports.errors import PermanentPortError, TransientPortError
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 10))
NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _request(**changes: object) -> RetrievalRequest:
    values: dict[str, object] = {
        "workspace_id": U[0],
        "attempt_id": U[8],
        "trace_id": UUID("018f0000-0000-7000-8000-000000000010"),
        "principal_class": PrincipalClass.HUMAN,
        "principal_id": U[2],
        "namespace_ids": (U[1],),
        "subjects": (
            RetrievalSubject(kind=NamespaceSubjectKind.WORKSPACE, id=U[0]),
            RetrievalSubject(kind=NamespaceSubjectKind.USER, id=U[2]),
        ),
        "query": "budget 2027",
        "query_vector": [1.0, 0.0],
        "embedding_model": "fixture-embed",
        "embedding_version": "1",
        "index_version": "fixture-index-1",
        "requested_at": NOW,
        "final_k": 2,
    }
    values.update(changes)
    return RetrievalRequest.model_validate(values)


def _candidate(chunk_id: UUID, score: float, *, text: str = "candidate") -> HybridCandidate:
    return HybridCandidate(
        namespace_id=U[1],
        chunk_id=chunk_id,
        document_id=U[6],
        source_id=U[7],
        citation="Fixture, 2026",
        text=text,
        source_content_hash=HASH_A,
        content_hash=HASH_B,
        locator={"page": 1, "char_start": 0, "char_end": 9},
        chunker_version="chunker-v1",
        source_timestamp=NOW,
        document_timestamp=NOW,
        retrieved_at=NOW,
        trust_level="SECONDARY",
        score=score,
    )


class StubCandidates:
    def __init__(
        self,
        lexical: tuple[HybridCandidate, ...] | Exception,
        vector: tuple[HybridCandidate, ...] | Exception,
    ) -> None:
        self.lexical_hits = lexical
        self.vector_hits = vector
        self.requests: list[RetrievalRequest] = []

    async def authorize(self, request: RetrievalRequest) -> tuple[UUID, ...]:
        return (request.namespace_ids[0],)

    async def lexical(self, request: RetrievalRequest, *, k: int) -> tuple[HybridCandidate, ...]:
        assert k == request.final_k * 3
        self.requests.append(request)
        if isinstance(self.lexical_hits, Exception):
            raise self.lexical_hits
        return self.lexical_hits

    async def vector(self, request: RetrievalRequest, *, k: int) -> tuple[HybridCandidate, ...]:
        assert k == request.final_k * 3
        self.requests.append(request)
        if isinstance(self.vector_hits, Exception):
            raise self.vector_hits
        return self.vector_hits


class BrokenReranker:
    version = "broken-v1"

    async def rerank(
        self, query: str, candidates: Sequence[RetrievedChunk], *, k: int
    ) -> Sequence[RetrievedChunk]:
        del query, candidates, k
        raise TransientPortError("timeout", port="reranker")


class StubAudit:
    def __init__(self, error: Exception | None = None) -> None:
        self.attempts: list[RetrievalAttempt] = []
        self.error = error

    async def append(self, attempt: RetrievalAttempt) -> None:
        if self.error is not None:
            raise self.error
        self.attempts.append(attempt)


@req("FR-409")
def test_request_fails_closed_for_implicit_scope_and_bad_principal() -> None:
    with pytest.raises(ValidationError, match="namespace_ids"):
        _request(namespace_ids=())
    with pytest.raises(ValidationError, match="include the request workspace"):
        _request(subjects=(RetrievalSubject(kind=NamespaceSubjectKind.USER, id=U[2]),))
    with pytest.raises(ValidationError, match="typed principal identity"):
        _request(principal_id=U[3])
    with pytest.raises(ValidationError, match="finite"):
        _request(query_vector=[float("nan")])


@req("FR-409")
def test_rrf_records_both_arm_scores_and_breaks_equal_fusion_by_uuid() -> None:
    first = _candidate(U[3], 0.8)
    second = _candidate(U[4], 0.7)

    fused = reciprocal_rank_fusion(
        (second, first), (first, second), index_version="fixture-index-1"
    )

    assert [hit.chunk_id for hit in fused] == [U[3], U[4]]
    assert fused[0].lexical_score == 0.8
    assert fused[0].vector_score == 0.8
    assert fused[0].fused_score == pytest.approx(1 / 62 + 1 / 61)
    assert fused[0].index_version == "fixture-index-1"


@req("FR-409")
async def test_retriever_records_census_query_identity_and_reranker_fallback() -> None:
    candidates = StubCandidates(
        (_candidate(U[3], 0.9), _candidate(U[4], 0.8)),
        (_candidate(U[4], 0.95),),
    )
    audit = StubAudit()
    result = await HybridRetriever(candidates, BrokenReranker(), audit).retrieve(_request())

    assert isinstance(candidates, CandidateSearch)
    assert isinstance(BrokenReranker(), Reranker)
    assert isinstance(audit, RetrievalAudit)
    assert (
        result.query_hash
        == "sha256:066de7cf2916ae920de825d1a9e8de268d81f80fd2e047143b4ce467dd4cd6f6"
    )
    assert result.lexical_count == 2
    assert result.vector_count == 1
    assert result.degradation is RetrievalDegradation.RERANKER_FAILED
    assert [hit.chunk_id for hit in result.chunks] == [U[4], U[3]]
    assert result.warnings == ("reranker failed; deterministic fused order retained",)
    assert len(audit.attempts) == 1
    attempt = audit.attempts[0]
    assert attempt.outcome is RetrievalOutcome.ALLOWED
    assert attempt.principal_id == U[2]
    assert attempt.requested_namespace_ids == (U[1],)
    assert attempt.searched_namespace_ids == (U[1],)
    assert attempt.result_chunk_ids == (U[4], U[3])
    assert attempt.result_content_hashes == (HASH_B, HASH_B)
    assert attempt.result_count == 2
    assert attempt.degradation is RetrievalDegradation.RERANKER_FAILED
    assert "query" not in attempt.model_dump()
    assert "text" not in attempt.model_dump()


@req("FR-409")
@pytest.mark.parametrize(
    ("error", "degradation"),
    [
        (
            TransientPortError("offline", port="candidate_search"),
            RetrievalDegradation.LEXICAL_ONLY,
        ),
        (
            IndexMismatchError("mismatch", port="candidate_search"),
            RetrievalDegradation.INDEX_MISMATCH,
        ),
    ],
)
async def test_vector_failure_retains_lexical_candidates(
    error: Exception, degradation: RetrievalDegradation
) -> None:
    result = await HybridRetriever(
        StubCandidates((_candidate(U[3], 0.9),), error), NoopReranker(), StubAudit()
    ).retrieve(_request())

    assert result.degradation is degradation
    assert result.vector_count == 0
    assert [hit.chunk_id for hit in result.chunks] == [U[3]]


@req("FR-409")
async def test_empty_authorized_scope_is_denied_before_scoring() -> None:
    candidates = StubCandidates((), ())

    async def deny(request: RetrievalRequest) -> tuple[UUID, ...]:
        del request
        return ()

    candidates.authorize = deny  # type: ignore[method-assign]
    audit = StubAudit()
    with pytest.raises(PermanentPortError, match="no requested namespace"):
        await HybridRetriever(candidates, NoopReranker(), audit).retrieve(_request())
    assert candidates.requests == []
    assert len(audit.attempts) == 1
    assert audit.attempts[0].outcome is RetrievalOutcome.DENIED
    assert audit.attempts[0].searched_namespace_ids == ()
    assert audit.attempts[0].result_chunk_ids == ()


@req("FR-409")
async def test_fr409_expected_match_no_hits_records_rag_failed() -> None:
    audit = StubAudit()

    with pytest.raises(RagFailed) as failure:
        await HybridRetriever(StubCandidates((), ()), NoopReranker(), audit).retrieve(
            _request(expected_match=True)
        )

    assert failure.value.code is ErrorCode.RAG_FAILED
    assert len(audit.attempts) == 1
    attempt = audit.attempts[0]
    assert attempt.outcome is RetrievalOutcome.RAG_FAILED
    assert attempt.searched_namespace_ids == (U[1],)
    assert attempt.result_count == 0
    assert attempt.degradation is RetrievalDegradation.NONE
    assert attempt.warnings == ("RAG_FAILED: expected match returned no candidates",)


@req("FR-409")
async def test_fr409_lexical_failure_records_rag_failed_instead_of_empty_result() -> None:
    audit = StubAudit()
    lexical_error = TransientPortError("database offline", port="candidate_search")

    with pytest.raises(RagFailed) as failure:
        await HybridRetriever(StubCandidates(lexical_error, ()), NoopReranker(), audit).retrieve(
            _request()
        )

    assert failure.value.code is ErrorCode.RAG_FAILED
    assert failure.value.__cause__ is lexical_error
    assert len(audit.attempts) == 1
    attempt = audit.attempts[0]
    assert attempt.outcome is RetrievalOutcome.RAG_FAILED
    assert attempt.searched_namespace_ids == (U[1],)
    assert attempt.result_count == 0
    assert attempt.warnings == ("RAG_FAILED: lexical retrieval did not complete",)


@req("FR-409")
async def test_empty_result_without_expected_match_is_successful_no_match() -> None:
    audit = StubAudit()

    result = await HybridRetriever(StubCandidates((), ()), NoopReranker(), audit).retrieve(
        _request(expected_match=False)
    )

    assert result.chunks == ()
    assert audit.attempts[0].outcome is RetrievalOutcome.ALLOWED


@req("FR-409")
@pytest.mark.parametrize("authorized", [True, False])
async def test_audit_failure_fails_retrieval_closed(authorized: bool) -> None:
    candidates = StubCandidates((_candidate(U[3], 0.9),), ())
    if not authorized:

        async def deny(request: RetrievalRequest) -> tuple[UUID, ...]:
            del request
            return ()

        candidates.authorize = deny  # type: ignore[method-assign]
    audit_error = TransientPortError("audit unavailable", port="retrieval_audit")
    with pytest.raises(TransientPortError, match="audit unavailable"):
        await HybridRetriever(candidates, NoopReranker(), StubAudit(audit_error)).retrieve(
            _request()
        )


@req("FR-409")
def test_lexical_index_and_candidate_sql_enforce_authorization_before_scoring() -> None:
    backend = Path(__file__).parents[2]
    migration = (backend / "alembic" / "versions" / "20260906_0013_hybrid_retrieval.py").read_text(
        encoding="utf-8"
    )
    adapter = (backend / "app" / "adapters" / "retrieval" / "postgres.py").read_text(
        encoding="utf-8"
    )

    assert "TSVECTOR" in migration
    assert "ix_chunks_search_vector_gin" in migration
    assert adapter.count("authorized_namespaces AS MATERIALIZED") == 1
    assert "supplied_subjects AS MATERIALIZED" in adapter
    assert "trusted_subjects AS MATERIALIZED" in adapter
    assert "session_agents" in adapter
    assert "JOIN session_lifecycles sl" in adapter
    assert "replacement.replaced_agent_def_id = sa.agent_def_id" in adapter
    assert "sai.effective_round <= sl.round" in adapter
    assert "replacement_event.ledger_seq > introduction_event.ledger_seq" in adapter
    assert all(
        f"WHEN '{tier}'" in adapter
        for tier in ("GLOBAL", "WORKSPACE", "DOMAIN", "AGENT", "SESSION", "HISTORICAL")
    )
    assert "g.capability = 'READ'" in adapter
    assert "g.valid_from <= :requested_at" in adapter
    assert "cardinality(c.acl) = 0 " in adapter
    assert "OR c.acl && ARRAY(SELECT subject_id FROM trusted_subjects)" in adapter
    assert adapter.index("authorized_namespaces AS MATERIALIZED") < adapter.index("ts_rank_cd")
