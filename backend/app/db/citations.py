"""PostgreSQL-authoritative citation resolution and source retraction."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.citations import EvidenceCitationRow, SourceRetractionRow
from app.domain.citations import (
    CitationError,
    CitationRepository,
    CitationResolution,
    CitationSnapshot,
    EvidenceCitation,
    ManualEvidenceCitation,
    SourceRetraction,
    SourceRetractionCommand,
)
from app.domain.knowledge import SourceStatus

__all__ = ["SqlAlchemyCitationRepository"]


# trace: FR-402, FR-407, FR-408
class SqlAlchemyCitationRepository:
    """Resolve every caller identity against PostgreSQL inside one transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def attach_manual(self, command: ManualEvidenceCitation) -> EvidenceCitation:
        result = await self._session.execute(
            text(
                """
                INSERT INTO evidence_citations (
                  id, workspace_id, session_id, evidence_artifact_id, claim_artifact_id,
                  actor_id, namespace_id, source_id, document_id, chunk_id, citation,
                  locator, source_content_hash, chunk_content_hash, chunker_version,
                  source_timestamp, document_timestamp, retrieved_at, trust_level, source_status
                )
                SELECT :id, e.workspace_id, e.session_id, e.id,
                  (e.payload ->> 'claim_id')::uuid, :actor_id, s.namespace_id, s.id, d.id, c.id,
                  s.citation, c.locator, s.content_hash, c.content_hash, c.chunker_version,
                  COALESCE(s.published_at, s.ingested_at), d.created_at, :retrieved_at,
                  s.trust_level, s.status
                FROM reasoning_artifacts e
                JOIN reasoning_artifacts claim
                  ON claim.workspace_id = e.workspace_id
                 AND claim.session_id = e.session_id
                 AND claim.id = (e.payload ->> 'claim_id')::uuid
                 AND claim.kind = 'CLAIM'
                JOIN sources s
                  ON s.workspace_id = e.workspace_id AND s.id = :source_id
                 AND s.namespace_id = :namespace_id
                JOIN documents d
                  ON d.workspace_id = s.workspace_id AND d.id = :document_id
                 AND d.source_id = s.id
                JOIN chunks c
                  ON c.workspace_id = d.workspace_id AND c.id = :chunk_id
                 AND c.document_id = d.id
                JOIN workspace_members member
                  ON member.workspace_id = e.workspace_id AND member.user_id = :actor_id
                JOIN users actor ON actor.id = member.user_id AND actor.is_active
                WHERE e.workspace_id = :workspace_id AND e.session_id = :session_id
                  AND e.id = :evidence_artifact_id AND e.kind = 'EVIDENCE'
                  AND e.owner_actor_class = 'HUMAN' AND e.owner_actor_id = :actor_id
                  AND e.provenance ->> 'origin' = 'HUMAN'
                  AND e.payload ->> 'provenance_kind' = 'HUMAN'
                  AND e.payload ->> 'trust_level' = s.trust_level
                  AND s.status = 'READY' AND d.status = 'READY'
                  AND s.content_hash = :source_content_hash
                  AND c.content_hash = :chunk_content_hash
                  AND c.locator = CAST(:locator AS jsonb)
                  AND EXISTS (
                    SELECT 1 FROM jsonb_array_elements(e.source_references) ref
                    WHERE ref ->> 'reference' = s.citation
                      AND ref -> 'locator' = c.locator
                      AND ref ->> 'content_hash' = c.content_hash
                      AND (ref ->> 'retrieved_at')::timestamptz = :retrieved_at
                      AND (ref ->> 'source_timestamp')::timestamptz =
                          COALESCE(s.published_at, s.ingested_at)
                  )
                RETURNING *
                """
            ),
            {
                "id": command.citation_id,
                "workspace_id": command.workspace_id,
                "session_id": command.session_id,
                "evidence_artifact_id": command.evidence_artifact_id,
                "actor_id": command.actor_id,
                "namespace_id": command.namespace_id,
                "source_id": command.source_id,
                "document_id": command.document_id,
                "chunk_id": command.chunk_id,
                "source_content_hash": command.source_content_hash,
                "chunk_content_hash": command.chunk_content_hash,
                "locator": json.dumps(command.locator, separators=(",", ":"), sort_keys=True),
                "retrieved_at": command.retrieved_at,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise CitationError(
                "manual evidence actor or source/document/chunk provenance did not resolve"
            )
        return _citation(cast(Mapping[str, Any], row))

    async def resolve(self, workspace_id: UUID, citation_id: UUID) -> CitationResolution | None:
        row = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT ec.*, s.status AS current_source_status,
                      sr.retracted_at AS current_retracted_at,
                      sr.reason AS current_retraction_reason
                    FROM evidence_citations ec
                    JOIN sources s
                      ON s.workspace_id = ec.workspace_id AND s.id = ec.source_id
                    LEFT JOIN source_retractions sr
                      ON sr.workspace_id = s.workspace_id AND sr.source_id = s.id
                    WHERE ec.workspace_id = :workspace_id AND ec.id = :citation_id
                    """
                    ),
                    {"workspace_id": workspace_id, "citation_id": citation_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return CitationResolution(
            citation=_citation(cast(Mapping[str, Any], row)),
            current_source_status=SourceStatus(row["current_source_status"]),
            retracted_at=row["current_retracted_at"],
            retraction_reason=row["current_retraction_reason"],
        )

    async def citations_for_evidence(
        self, workspace_id: UUID, evidence_artifact_id: UUID
    ) -> tuple[CitationResolution, ...]:
        """Resolve every canonical chunk citation for an evidence artifact.

        The schema permits one evidence artifact to cite multiple chunks and only
        enforces uniqueness per evidence/chunk pair, so this is intentionally a
        deterministically ordered collection rather than a lossy single lookup.
        """
        rows = (
            await self._session.execute(
                text(
                    """
                    SELECT ec.*, s.status AS current_source_status,
                      sr.retracted_at AS current_retracted_at,
                      sr.reason AS current_retraction_reason
                    FROM evidence_citations ec
                    JOIN sources s
                      ON s.workspace_id = ec.workspace_id AND s.id = ec.source_id
                    LEFT JOIN source_retractions sr
                      ON sr.workspace_id = s.workspace_id AND sr.source_id = s.id
                    WHERE ec.workspace_id = :workspace_id
                      AND ec.evidence_artifact_id = :evidence_artifact_id
                    ORDER BY ec.attached_at, ec.id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "evidence_artifact_id": evidence_artifact_id,
                },
            )
        ).mappings()
        return tuple(
            CitationResolution(
                citation=_citation(cast(Mapping[str, Any], row)),
                current_source_status=SourceStatus(row["current_source_status"]),
                retracted_at=row["current_retracted_at"],
                retraction_reason=row["current_retraction_reason"],
            )
            for row in rows
        )

    async def retract_source(self, command: SourceRetractionCommand) -> SourceRetraction:
        source_id = await self._session.scalar(
            text(
                """
                UPDATE sources s
                SET status = 'RETRACTED', retracted_at = :retracted_at,
                    retraction_reason = :reason
                WHERE s.workspace_id = :workspace_id AND s.id = :source_id
                  AND s.status <> 'RETRACTED'
                  AND EXISTS (
                    SELECT 1 FROM workspace_members m JOIN users u ON u.id = m.user_id
                    WHERE m.workspace_id = s.workspace_id AND m.user_id = :actor_id
                      AND u.is_active
                  )
                RETURNING s.id
                """
            ),
            {
                "workspace_id": command.workspace_id,
                "source_id": command.source_id,
                "actor_id": command.actor_id,
                "reason": command.reason,
                "retracted_at": command.retracted_at,
            },
        )
        if source_id is None:
            raise CitationError(
                "source does not exist, actor is invalid, or source is already retracted"
            )
        self._session.add(
            SourceRetractionRow(
                id=command.retraction_id,
                workspace_id=command.workspace_id,
                source_id=command.source_id,
                actor_id=command.actor_id,
                reason=command.reason,
                retracted_at=command.retracted_at,
            )
        )
        await self._session.flush()
        citations = await self.dependencies(command.workspace_id, command.source_id)
        return SourceRetraction(
            retraction_id=command.retraction_id,
            workspace_id=command.workspace_id,
            source_id=command.source_id,
            actor_id=command.actor_id,
            reason=command.reason,
            retracted_at=command.retracted_at,
            dependent_evidence_ids=tuple(
                sorted({citation.evidence_artifact_id for citation in citations}, key=str)
            ),
            dependent_claim_ids=tuple(
                sorted({citation.claim_artifact_id for citation in citations}, key=str)
            ),
        )

    async def dependencies(
        self, workspace_id: UUID, source_id: UUID
    ) -> tuple[EvidenceCitation, ...]:
        rows = (
            await self._session.execute(
                select(EvidenceCitationRow)
                .where(
                    EvidenceCitationRow.workspace_id == workspace_id,
                    EvidenceCitationRow.source_id == source_id,
                )
                .order_by(EvidenceCitationRow.attached_at, EvidenceCitationRow.id)
            )
        ).scalars()
        return tuple(_citation_from_model(row) for row in rows)


def _citation(row: Mapping[str, Any]) -> EvidenceCitation:
    return EvidenceCitation(
        citation_id=row["id"],
        workspace_id=row["workspace_id"],
        session_id=row["session_id"],
        evidence_artifact_id=row["evidence_artifact_id"],
        claim_artifact_id=row["claim_artifact_id"],
        actor_id=row["actor_id"],
        attached_at=row["attached_at"],
        snapshot=_snapshot(row),
    )


def _citation_from_model(row: EvidenceCitationRow) -> EvidenceCitation:
    values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    return _citation(values)


def _snapshot(row: Mapping[str, Any]) -> CitationSnapshot:
    return CitationSnapshot(
        namespace_id=row["namespace_id"],
        source_id=row["source_id"],
        document_id=row["document_id"],
        chunk_id=row["chunk_id"],
        citation=row["citation"],
        locator=dict(row["locator"]),
        source_content_hash=row["source_content_hash"],
        chunk_content_hash=row["chunk_content_hash"],
        chunker_version=row["chunker_version"],
        source_timestamp=row["source_timestamp"],
        document_timestamp=row["document_timestamp"],
        retrieved_at=row["retrieved_at"],
        trust_level=row["trust_level"],
        source_status=SourceStatus(row["source_status"]),
    )


_CITATION_REPOSITORY_PORT: type[CitationRepository] = SqlAlchemyCitationRepository
