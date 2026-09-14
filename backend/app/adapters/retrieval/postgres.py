"""PostgreSQL hybrid candidate search with authorization inside scoring SQL."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.domain.retrieval import (
    CandidateSearch,
    HybridCandidate,
    IndexMismatchError,
    RetrievalRequest,
)
from app.ports.errors import PermanentPortError, TransientPortError

__all__ = ["PostgresCandidateSearch"]

_PORT = "candidate_search"
_DIMENSIONS = 1536
_TRANSIENT_SQLSTATES = frozenset({"40001", "40P01", "55P03", "57014"})
_AUTHORIZATION_CTE = """
WITH supplied_subjects AS MATERIALIZED (
  SELECT subject_kind, subject_id
  FROM unnest(CAST(:subject_kinds AS text[]), CAST(:subject_ids AS uuid[]))
    AS supplied(subject_kind, subject_id)
), trusted_subjects AS MATERIALIZED (
  SELECT subject_kind, subject_id
  FROM supplied_subjects s
  WHERE (s.subject_kind = 'WORKSPACE' AND s.subject_id = :workspace_id)
     OR (s.subject_kind = 'USER' AND :principal_class = 'HUMAN'
         AND s.subject_id = :principal_id AND EXISTS (
           SELECT 1 FROM users u
           JOIN workspace_members m ON m.user_id = u.id
           WHERE u.id = s.subject_id
             AND m.workspace_id = :workspace_id
         ))
     OR (s.subject_kind = 'AGENT_DEFINITION' AND :principal_class = 'AGENT'
         AND s.subject_id = :principal_id AND EXISTS (
           SELECT 1 FROM agent_definitions a
           WHERE a.id = s.subject_id AND a.workspace_id = :workspace_id
             AND a.status IN ('ACTIVE', 'DEPRECATED')
         ))
     OR (s.subject_kind = 'SESSION' AND EXISTS (
           SELECT 1 FROM sessions se
           WHERE se.id = s.subject_id AND se.workspace_id = :workspace_id
             AND ((:principal_class = 'HUMAN' AND se.created_by = :principal_id)
               OR (:principal_class = 'AGENT' AND EXISTS (
                 SELECT 1 FROM session_agents sa
                  JOIN session_lifecycles sl
                    ON sl.workspace_id = sa.workspace_id AND sl.session_id = sa.session_id
                 WHERE sa.workspace_id = se.workspace_id AND sa.session_id = se.id
                   AND sa.agent_def_id = :principal_id
                    AND NOT EXISTS (
                      SELECT 1 FROM session_agent_interventions replacement
                      WHERE replacement.workspace_id = sa.workspace_id
                        AND replacement.session_id = sa.session_id
                        AND replacement.kind = 'REPLACE'
                        AND replacement.replaced_agent_def_id = sa.agent_def_id
                        AND replacement.effective_round <= sl.round
                    )
                  UNION ALL
                  SELECT 1 FROM session_agent_interventions sai
                  JOIN session_lifecycles sl
                    ON sl.workspace_id = sai.workspace_id AND sl.session_id = sai.session_id
                  JOIN reasoning_events introduction_event
                    ON introduction_event.workspace_id = sai.workspace_id
                   AND introduction_event.session_id = sai.session_id
                   AND introduction_event.id = sai.event_id
                  WHERE sai.workspace_id = se.workspace_id AND sai.session_id = se.id
                    AND sai.agent_def_id = :principal_id
                    AND sai.effective_round <= sl.round
                    AND NOT EXISTS (
                      SELECT 1 FROM session_agent_interventions replacement
                      JOIN reasoning_events replacement_event
                        ON replacement_event.workspace_id = replacement.workspace_id
                       AND replacement_event.session_id = replacement.session_id
                       AND replacement_event.id = replacement.event_id
                      WHERE replacement.workspace_id = sai.workspace_id
                        AND replacement.session_id = sai.session_id
                        AND replacement.kind = 'REPLACE'
                        AND replacement.replaced_agent_def_id = sai.agent_def_id
                        AND replacement.effective_round <= sl.round
                        AND replacement_event.ledger_seq > introduction_event.ledger_seq
                    )
               )))
         ))
), authorized_namespaces AS MATERIALIZED (
  SELECT DISTINCT n.id AS namespace_id
  FROM knowledge_namespaces n
  JOIN knowledge_namespace_grants g
    ON g.workspace_id = n.workspace_id AND g.namespace_id = n.id
  JOIN trusted_subjects t
    ON t.subject_kind = g.subject_kind AND t.subject_id = g.subject_id
  WHERE n.workspace_id = :workspace_id
    AND n.id = ANY(CAST(:namespace_ids AS uuid[]))
    AND g.capability = 'READ' AND g.valid_from <= :requested_at
    AND (g.valid_until IS NULL OR g.valid_until > :requested_at)
    AND (SELECT count(*) FROM supplied_subjects) = (SELECT count(*) FROM trusted_subjects)
    AND CASE n.tier
      WHEN 'GLOBAL' THEN g.subject_kind IN ('WORKSPACE', 'USER', 'AGENT_DEFINITION')
      WHEN 'WORKSPACE' THEN g.subject_kind IN ('WORKSPACE', 'USER', 'AGENT_DEFINITION')
      WHEN 'DOMAIN' THEN g.subject_kind = 'AGENT_DEFINITION'
        AND :principal_class = 'AGENT' AND g.subject_id = :principal_id AND EXISTS (
        SELECT 1 FROM agent_definitions a
        WHERE a.workspace_id = n.workspace_id AND a.id = :principal_id
          AND n.id = ANY(a.knowledge_ns)
      )
      WHEN 'AGENT' THEN g.subject_kind = 'AGENT_DEFINITION'
        AND :principal_class = 'AGENT' AND g.subject_id = :principal_id
        AND n.agent_def_id = :principal_id
      WHEN 'SESSION' THEN g.subject_kind = 'SESSION' AND g.subject_id = n.session_id
      WHEN 'HISTORICAL' THEN g.subject_kind = 'AGENT_DEFINITION'
        AND :principal_class = 'AGENT' AND g.subject_id = :principal_id AND EXISTS (
        SELECT 1 FROM agent_definitions a
        WHERE a.workspace_id = n.workspace_id AND a.id = :principal_id
          AND n.id = ANY(a.knowledge_ns)
      )
      ELSE false
    END
)
"""
_AUTHORIZED_COLUMNS = """
  s.namespace_id, c.id AS chunk_id, d.id AS document_id, s.id AS source_id,
  s.citation, c.text, c.search_vector, s.content_hash AS source_content_hash, c.content_hash,
  c.locator, c.chunker_version,
  COALESCE(s.published_at, s.ingested_at) AS source_timestamp,
  d.created_at AS document_timestamp, :requested_at AS retrieved_at, s.trust_level
"""
_RESULT_COLUMNS = """
  namespace_id, chunk_id, document_id, source_id, citation, text, source_content_hash,
  content_hash, locator, chunker_version, source_timestamp, document_timestamp,
  retrieved_at, trust_level
"""


# trace: FR-402, FR-404, FR-405
class PostgresCandidateSearch:
    def __init__(self, engine: AsyncEngine, workspace_id: UUID) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._workspace_id = workspace_id

    async def authorize(self, request: RetrievalRequest) -> tuple[UUID, ...]:
        sql = text(
            """
"""
            + _AUTHORIZATION_CTE
            + """
SELECT namespace_id FROM authorized_namespaces ORDER BY namespace_id
"""
        )
        rows = await self._execute(sql, request, extra={})
        return tuple(row["namespace_id"] for row in rows)

    async def lexical(self, request: RetrievalRequest, *, k: int) -> tuple[HybridCandidate, ...]:
        sql = text(
            _AUTHORIZATION_CTE
            + ", authorized AS MATERIALIZED (SELECT "
            + _AUTHORIZED_COLUMNS
            + """
FROM chunks c
JOIN documents d ON d.workspace_id = c.workspace_id AND d.id = c.document_id
JOIN sources s ON s.workspace_id = d.workspace_id AND s.id = d.source_id
JOIN authorized_namespaces an ON an.namespace_id = s.namespace_id
WHERE c.workspace_id = :workspace_id
  AND s.status = 'READY' AND d.status = 'READY'
"""
            + "  AND (cardinality(c.acl) = 0 "
            + "OR c.acl && ARRAY(SELECT subject_id FROM trusted_subjects))\n"
            + ") SELECT "
            + _RESULT_COLUMNS
            + """,
  (ts_rank_cd(search_vector, websearch_to_tsquery('simple', :query))
   + similarity(text, :query)) AS score
FROM authorized
WHERE search_vector @@ websearch_to_tsquery('simple', :query)
   OR similarity(text, :query) > :min_score
ORDER BY score DESC, chunk_id ASC
LIMIT :k
"""
        )
        rows = await self._execute(
            sql,
            request,
            extra={"query": request.query, "min_score": request.lexical_min_score, "k": k},
        )
        return tuple(HybridCandidate(**dict(row)) for row in rows)

    async def vector(self, request: RetrievalRequest, *, k: int) -> tuple[HybridCandidate, ...]:
        if len(request.query_vector) != _DIMENSIONS:
            raise PermanentPortError("query vector must have 1536 dimensions", port=_PORT)
        sql = text(
            _AUTHORIZATION_CTE
            + ", authorized AS MATERIALIZED (SELECT "
            + _AUTHORIZED_COLUMNS
            + """, v.embedding
FROM vector_items v
JOIN chunks c ON c.workspace_id = v.workspace_id AND c.id = v.chunk_uuid
JOIN documents d ON d.workspace_id = c.workspace_id AND d.id = c.document_id
JOIN sources s ON s.workspace_id = d.workspace_id AND s.id = d.source_id
JOIN authorized_namespaces an ON an.namespace_id = s.namespace_id
WHERE c.workspace_id = :workspace_id
  AND s.status = 'READY' AND d.status = 'READY' AND v.content_hash = c.content_hash
  AND v.embedding_model = :embedding_model AND v.embedding_version = :embedding_version
"""
            + "  AND (cardinality(c.acl) = 0 "
            + "OR c.acl && ARRAY(SELECT subject_id FROM trusted_subjects))\n"
            + ") SELECT "
            + _RESULT_COLUMNS
            + """,
  (1 - (embedding <=> CAST(:embedding AS vector))) AS score
FROM authorized
WHERE (1 - (embedding <=> CAST(:embedding AS vector))) >= :min_score
ORDER BY score DESC, chunk_id ASC
LIMIT :k
"""
        )
        rows = await self._execute(
            sql,
            request,
            extra={
                "embedding": str(list(request.query_vector)),
                "embedding_model": request.embedding_model,
                "embedding_version": request.embedding_version,
                "min_score": request.vector_min_score,
                "k": k,
            },
            verify_index_identity=True,
        )
        return tuple(HybridCandidate(**dict(row)) for row in rows)

    async def _execute(
        self,
        sql: Any,
        request: RetrievalRequest,
        *,
        extra: dict[str, object],
        verify_index_identity: bool = False,
    ) -> tuple[RowMapping, ...]:
        if request.workspace_id != self._workspace_id:
            raise PermanentPortError("retrieval workspace does not match adapter scope", port=_PORT)
        parameters: dict[str, object] = {
            "workspace_id": self._workspace_id,
            "namespace_ids": list(request.namespace_ids),
            "principal_class": request.principal_class.value,
            "principal_id": request.principal_id,
            "subject_kinds": [subject.kind.value for subject in request.subjects],
            "subject_ids": [subject.id for subject in request.subjects],
            "requested_at": request.requested_at,
            **extra,
        }
        try:
            async with self._sessions.begin() as session:
                await session.execute(
                    text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                    {"workspace_id": str(self._workspace_id)},
                )
                if verify_index_identity:
                    identities = (
                        await session.execute(
                            text(
                                _AUTHORIZATION_CTE
                                + " SELECT DISTINCT v.embedding_model, v.embedding_version "
                                "FROM vector_items v JOIN authorized_namespaces an "
                                "ON an.namespace_id = v.namespace_id "
                                "WHERE v.workspace_id = :workspace_id"
                            ),
                            parameters,
                        )
                    ).tuples()
                    _require_index_identity(
                        set(identities), request.embedding_model, request.embedding_version
                    )
                return tuple((await session.execute(sql, parameters)).mappings())
        except PermanentPortError:
            raise
        except DBAPIError as exc:
            error = (
                TransientPortError
                if exc.connection_invalidated
                or getattr(exc.orig, "sqlstate", None) in _TRANSIENT_SQLSTATES
                else PermanentPortError
            )
            raise error("PostgreSQL candidate search failed", port=_PORT, cause=exc) from exc
        except SQLAlchemyError as exc:
            raise TransientPortError(
                "PostgreSQL candidate search failed", port=_PORT, cause=exc
            ) from exc


_CANDIDATE_SEARCH_PORT: type[CandidateSearch] = PostgresCandidateSearch


def _require_index_identity(
    identities: set[tuple[str | None, str | None]], model: str, version: str
) -> None:
    if identities - {(model, version)}:
        raise IndexMismatchError(
            "embedding model/version does not match the namespace index", port=_PORT
        )
