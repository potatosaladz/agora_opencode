"""SQLAlchemy implementation of typed reasoning-artifact persistence."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.reasoning import ReasoningArtifactRow
from app.domain.artifact_commit import AgentProposalStore, ReasoningArtifactStore
from app.domain.phase3_api import Phase3ArtifactStore
from app.domain.reasoning import LifecycleStatus, ReasoningArtifact, validate_artifact_json

__all__ = ["SqlAlchemyReasoningArtifactStore"]


# trace: FR-302
def _from_row(row: ReasoningArtifactRow) -> ReasoningArtifact:
    return validate_artifact_json(
        json.dumps(
            {
                "id": row.id,
                "workspace_id": row.workspace_id,
                "session_id": row.session_id,
                "logical_id": row.logical_id,
                "kind": row.kind,
                "schema_version": row.schema_version,
                "version": row.version,
                "status": row.status,
                "supersedes_id": row.supersedes_id,
                "owner_actor_class": row.owner_actor_class,
                "owner_actor_id": row.owner_actor_id,
                "round": row.round,
                "payload": row.payload,
                "provenance": row.provenance,
                "source_references": row.source_references,
                "parent_relationships": row.parent_relationships,
                "confidence": row.confidence,
                "metadata": row.artifact_metadata,
                "content_hash": row.content_hash,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            },
            default=str,
        )
    )


class SqlAlchemyReasoningArtifactStore:
    """Persist typed artifacts inside a caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_agent_turn(self, workspace_id: UUID, session_id: UUID, turn_id: UUID) -> None:
        """Serialize exact-turn retries until the caller transaction ends."""
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": f"agent-turn:{workspace_id}:{session_id}:{turn_id}"},
        )

    async def add(self, artifact: ReasoningArtifact) -> None:
        data: dict[str, Any] = artifact.model_dump(mode="json")
        self._session.add(
            ReasoningArtifactRow(
                id=artifact.id,
                workspace_id=artifact.workspace_id,
                session_id=artifact.session_id,
                logical_id=artifact.logical_id,
                kind=artifact.kind.value,
                schema_version=artifact.schema_version,
                version=artifact.version,
                status=artifact.status.value,
                supersedes_id=artifact.supersedes_id,
                owner_actor_class=artifact.owner_actor_class.value,
                owner_actor_id=artifact.owner_actor_id,
                round=artifact.round,
                payload=data["payload"],
                provenance=data["provenance"],
                source_references=data["source_references"],
                parent_relationships=data["parent_relationships"],
                confidence=data["confidence"],
                artifact_metadata=data["metadata"],
                content_hash=artifact.content_hash,
                created_at=artifact.created_at,
                updated_at=artifact.updated_at,
            )
        )
        await self._session.flush()

    async def get(
        self, workspace_id: UUID, artifact_id: UUID, *, session_id: UUID | None = None
    ) -> ReasoningArtifact | None:
        query = select(ReasoningArtifactRow).where(
            ReasoningArtifactRow.workspace_id == workspace_id,
            ReasoningArtifactRow.id == artifact_id,
        )
        if session_id is not None:
            query = query.where(ReasoningArtifactRow.session_id == session_id)
        row = await self._session.scalar(query)
        return _from_row(row) if row is not None else None

    async def get_for_update(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> ReasoningArtifact | None:
        row = await self._session.scalar(
            select(ReasoningArtifactRow)
            .where(
                ReasoningArtifactRow.workspace_id == workspace_id,
                ReasoningArtifactRow.session_id == session_id,
                ReasoningArtifactRow.id == artifact_id,
            )
            .with_for_update()
        )
        return _from_row(row) if row is not None else None

    async def set_lifecycle(
        self,
        workspace_id: UUID,
        session_id: UUID,
        artifact_id: UUID,
        status: LifecycleStatus,
        *,
        updated_at: datetime,
    ) -> None:
        row = await self._session.scalar(
            select(ReasoningArtifactRow).where(
                ReasoningArtifactRow.workspace_id == workspace_id,
                ReasoningArtifactRow.session_id == session_id,
                ReasoningArtifactRow.id == artifact_id,
            )
        )
        if row is None:
            raise ValueError(f"artifact {artifact_id} does not exist in the tenant session")
        row.status = status.value
        row.updated_at = updated_at
        await self._session.flush()


_ARTIFACT_STORE_PORT: type[ReasoningArtifactStore] = SqlAlchemyReasoningArtifactStore
_AGENT_PROPOSAL_STORE_PORT: type[AgentProposalStore] = SqlAlchemyReasoningArtifactStore
_PHASE3_ARTIFACT_STORE_PORT: type[Phase3ArtifactStore] = SqlAlchemyReasoningArtifactStore
