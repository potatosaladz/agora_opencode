"""Deterministic hybrid retrieval fusion and reranker degradation policy."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from app.common.errors import RagFailed
from app.domain.retrieval import (
    CandidateSearch,
    HybridCandidate,
    IndexMismatchError,
    Reranker,
    RetrievalAttempt,
    RetrievalAudit,
    RetrievalDegradation,
    RetrievalOutcome,
    RetrievalRequest,
    RetrievalResult,
    RetrievedChunk,
)
from app.ports.errors import PermanentPortError, PortError, TransientPortError

__all__ = ["HybridRetriever", "NoopReranker", "reciprocal_rank_fusion"]

_RRF_K0 = 60


# trace: FR-409
class NoopReranker:
    version = "noop-v1"

    async def rerank(
        self, query: str, candidates: Sequence[RetrievedChunk], *, k: int
    ) -> Sequence[RetrievedChunk]:
        del query
        return tuple(candidates[:k])


class HybridRetriever:
    def __init__(
        self, candidates: CandidateSearch, reranker: Reranker, audit: RetrievalAudit
    ) -> None:
        self._candidates = candidates
        self._reranker = reranker
        self._audit = audit

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        try:
            authorized_namespace_ids = await self._candidates.authorize(request)
        except PortError as exc:
            await self._audit.append(
                _attempt(
                    request,
                    outcome=RetrievalOutcome.RAG_FAILED,
                    reranker_version=None,
                    warnings=("RAG_FAILED: namespace authorization did not complete",),
                )
            )
            raise RagFailed("retrieval authorization did not complete", cause=exc) from exc
        if not authorized_namespace_ids:
            await self._audit.append(
                _attempt(request, outcome=RetrievalOutcome.DENIED, reranker_version=None)
            )
            raise PermanentPortError(
                "no requested namespace is authorized for retrieval", port="candidate_search"
            )
        scoped_request = request.model_copy(update={"namespace_ids": authorized_namespace_ids})
        arm_k = request.final_k * 3
        try:
            lexical = tuple(await self._candidates.lexical(scoped_request, k=arm_k))
        except PortError as exc:
            await self._audit.append(
                _attempt(
                    request,
                    outcome=RetrievalOutcome.RAG_FAILED,
                    reranker_version=None,
                    searched_namespace_ids=authorized_namespace_ids,
                    warnings=("RAG_FAILED: lexical retrieval did not complete",),
                )
            )
            raise RagFailed("retrieval did not complete", cause=exc) from exc
        degradation = RetrievalDegradation.NONE
        warnings: list[str] = []
        try:
            vector = tuple(await self._candidates.vector(scoped_request, k=arm_k))
        except TransientPortError:
            vector = ()
            degradation = RetrievalDegradation.LEXICAL_ONLY
            warnings.append("vector retrieval unavailable; lexical candidates retained")
        except IndexMismatchError:
            vector = ()
            degradation = RetrievalDegradation.INDEX_MISMATCH
            warnings.append("vector index identity mismatch; lexical candidates retained")
        except PortError as exc:
            await self._audit.append(
                _attempt(
                    request,
                    outcome=RetrievalOutcome.RAG_FAILED,
                    reranker_version=None,
                    searched_namespace_ids=authorized_namespace_ids,
                    lexical_count=len(lexical),
                    warnings=("RAG_FAILED: vector retrieval did not complete",),
                )
            )
            raise RagFailed("retrieval did not complete", cause=exc) from exc

        fused = reciprocal_rank_fusion(lexical, vector, index_version=request.index_version)
        selected = tuple(fused[: request.final_k])
        try:
            reranked = tuple(await self._reranker.rerank(request.query, fused, k=request.final_k))
            _validate_reranker_output(reranked, fused, request.final_k)
            selected = reranked
        except PortError:
            degradation = RetrievalDegradation.RERANKER_FAILED
            warnings.append("reranker failed; deterministic fused order retained")

        result = RetrievalResult(
            query_hash="sha256:" + sha256(request.query.encode()).hexdigest(),
            requested_namespace_ids=request.namespace_ids,
            searched_namespace_ids=authorized_namespace_ids,
            index_version=request.index_version,
            embedding_model=request.embedding_model,
            embedding_version=request.embedding_version,
            reranker_version=self._reranker.version,
            lexical_count=len(lexical),
            vector_count=len(vector),
            degradation=degradation,
            warnings=tuple(warnings),
            chunks=selected,
        )
        if request.expected_match and not result.chunks:
            await self._audit.append(
                _attempt(
                    request,
                    outcome=RetrievalOutcome.RAG_FAILED,
                    reranker_version=self._reranker.version,
                    result=result,
                    warnings=(
                        *result.warnings,
                        "RAG_FAILED: expected match returned no candidates",
                    ),
                )
            )
            raise RagFailed("retrieval expected a match but returned no candidates")
        await self._audit.append(
            _attempt(
                request,
                outcome=RetrievalOutcome.ALLOWED,
                reranker_version=self._reranker.version,
                result=result,
            )
        )
        return result


def _attempt(
    request: RetrievalRequest,
    *,
    outcome: RetrievalOutcome,
    reranker_version: str | None,
    result: RetrievalResult | None = None,
    searched_namespace_ids: tuple[UUID, ...] = (),
    lexical_count: int = 0,
    vector_count: int = 0,
    warnings: tuple[str, ...] = (),
) -> RetrievalAttempt:
    return RetrievalAttempt(
        attempt_id=request.attempt_id,
        trace_id=request.trace_id,
        workspace_id=request.workspace_id,
        principal_class=request.principal_class,
        principal_id=request.principal_id,
        requested_at=request.requested_at,
        completed_at=datetime.now(UTC),
        query_hash="sha256:" + sha256(request.query.encode()).hexdigest(),
        requested_namespace_ids=request.namespace_ids,
        searched_namespace_ids=(
            result.searched_namespace_ids if result else searched_namespace_ids
        ),
        result_chunk_ids=tuple(chunk.chunk_id for chunk in result.chunks) if result else (),
        result_content_hashes=tuple(chunk.content_hash for chunk in result.chunks)
        if result
        else (),
        index_version=request.index_version,
        embedding_model=request.embedding_model,
        embedding_version=request.embedding_version,
        reranker_version=reranker_version,
        lexical_count=result.lexical_count if result else lexical_count,
        vector_count=result.vector_count if result else vector_count,
        result_count=len(result.chunks) if result else 0,
        outcome=outcome,
        degradation=result.degradation if result else None,
        warnings=warnings or (result.warnings if result else ()),
    )


def reciprocal_rank_fusion(
    lexical: Sequence[HybridCandidate],
    vector: Sequence[HybridCandidate],
    *,
    index_version: str,
) -> tuple[RetrievedChunk, ...]:
    candidates: dict[object, HybridCandidate] = {}
    lexical_scores: dict[object, float] = {}
    vector_scores: dict[object, float] = {}
    fused_scores: dict[object, float] = {}
    for arm, scores in ((lexical, lexical_scores), (vector, vector_scores)):
        for rank, candidate in enumerate(arm, start=1):
            key = candidate.chunk_id
            candidates.setdefault(key, candidate)
            scores[key] = candidate.score
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (_RRF_K0 + rank)
    ordered_ids = sorted(
        candidates,
        key=lambda key: (-fused_scores[key], str(key)),
    )
    return tuple(
        RetrievedChunk(
            **candidates[key].model_dump(exclude={"score"}),
            score=fused_scores[key],
            lexical_score=lexical_scores.get(key),
            vector_score=vector_scores.get(key),
            fused_score=fused_scores[key],
            index_version=index_version,
        )
        for key in ordered_ids
    )


def _validate_reranker_output(
    reranked: Sequence[RetrievedChunk], candidates: Sequence[RetrievedChunk], k: int
) -> None:
    expected = {candidate.chunk_id for candidate in candidates}
    actual = [candidate.chunk_id for candidate in reranked]
    required_count = min(k, len(candidates))
    if (
        len(actual) != required_count
        or len(actual) != len(set(actual))
        or not set(actual) <= expected
    ):
        raise PermanentPortError("reranker returned invalid candidates", port="reranker")
    originals = {candidate.chunk_id: candidate for candidate in candidates}
    for candidate in reranked:
        original = originals[candidate.chunk_id]
        if candidate.model_dump(exclude={"rerank_score"}) != original.model_dump(
            exclude={"rerank_score"}
        ):
            raise PermanentPortError(
                "reranker changed immutable candidate provenance", port="reranker"
            )
