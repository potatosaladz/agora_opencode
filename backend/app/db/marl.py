"""PostgreSQL adapter for caller-transaction-owned MARL trajectory persistence."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.marl import MarlEpisodeRow, MarlRecordRow
from app.domain.marl import (
    DecisionBoundaryV1,
    EpisodeStatus,
    IncompleteMarkerV1,
    MarlConflictError,
    MarlDomainError,
    MarlEpisodeV1,
    TransitionV1,
)
from app.domain.reasoning import canonical_json

__all__ = ["SqlAlchemyMarlTrajectoryStore"]


def _payload(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value.model_dump(mode="json"))


class SqlAlchemyMarlTrajectoryStore:
    """Flush-only adapter; transaction commit/rollback belongs to its caller."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, episode: MarlEpisodeV1) -> MarlEpisodeV1:
        if (
            episode.status is not EpisodeStatus.OPEN
            or episode.transitions
            or episode.pending_boundary
        ):
            raise MarlDomainError("new episode must be empty and OPEN")
        current = await self.get(episode.workspace_id, episode.episode_id)
        if current is not None:
            if current == episode:
                return current
            raise MarlConflictError("episode identity conflicts with existing content")
        self._session.add(
            MarlEpisodeRow(
                id=episode.episode_id,
                workspace_id=episode.workspace_id,
                session_id=episode.session_id,
                schema_version=episode.schema_version,
                environment_version=episode.environment_version,
                code_identity=episode.code_identity,
                status=episode.status.value,
                incomplete_marker=None,
                incomplete_hash=None,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise MarlConflictError("episode persistence conflict") from exc
        return episode

    async def get(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeV1 | None:
        row = await self._session.scalar(
            select(MarlEpisodeRow).where(
                MarlEpisodeRow.workspace_id == workspace_id, MarlEpisodeRow.id == episode_id
            )
        )
        if row is None:
            return None
        records = list(
            (
                await self._session.scalars(
                    select(MarlRecordRow)
                    .where(
                        MarlRecordRow.workspace_id == workspace_id,
                        MarlRecordRow.episode_id == episode_id,
                    )
                    .order_by(MarlRecordRow.decision_index, MarlRecordRow.record_kind)
                )
            ).all()
        )
        transitions = tuple(
            TransitionV1.model_validate_json(canonical_json(item.payload))
            for item in records
            if item.record_kind == "TRANSITION"
        )
        closed_indexes = {item.decision_index for item in transitions}
        boundaries = tuple(
            DecisionBoundaryV1.model_validate_json(canonical_json(item.payload))
            for item in records
            if item.record_kind == "DECISION_BOUNDARY" and item.decision_index not in closed_indexes
        )
        marker = (
            IncompleteMarkerV1.model_validate_json(canonical_json(row.incomplete_marker))
            if row.incomplete_marker is not None
            else None
        )
        return MarlEpisodeV1(
            episode_id=row.id,
            workspace_id=row.workspace_id,
            session_id=row.session_id,
            environment_version=row.environment_version,
            code_identity=row.code_identity,
            status=EpisodeStatus(row.status),
            transitions=transitions,
            pending_boundary=boundaries[-1] if boundaries else None,
            incomplete_marker=marker,
        )

    async def capture(self, workspace_id: UUID, boundary: DecisionBoundaryV1) -> MarlEpisodeV1:
        episode = await self._locked(workspace_id, boundary.episode_id)
        if episode.status is not EpisodeStatus.OPEN:
            raise MarlConflictError("finalized episode cannot accept a boundary")
        existing = await self._record(
            workspace_id,
            boundary.episode_id,
            boundary.decision_index,
            "DECISION_BOUNDARY",
        )
        if existing is not None:
            if existing.record_hash == boundary.boundary_hash:
                return await self._required(workspace_id, boundary.episode_id)
            raise MarlConflictError("boundary identity conflicts with existing content")
        if episode.pending_boundary is not None or boundary.decision_index != len(
            episode.transitions
        ):
            raise MarlConflictError("boundary index is not the next gapless index")
        self._session.add(
            MarlRecordRow(
                id=boundary.coordinator_decision.decision_id,
                workspace_id=workspace_id,
                session_id=episode.session_id,
                episode_id=episode.episode_id,
                decision_index=boundary.decision_index,
                record_kind="DECISION_BOUNDARY",
                record_hash=boundary.boundary_hash,
                payload=_payload(boundary),
            )
        )
        await self._flush_conflict("boundary persistence conflict")
        return await self._required(workspace_id, boundary.episode_id)

    async def close(self, workspace_id: UUID, transition: TransitionV1) -> MarlEpisodeV1:
        episode = await self._locked(workspace_id, transition.episode_id)
        existing = await self._record(
            workspace_id, transition.episode_id, transition.decision_index, "TRANSITION"
        )
        if existing is not None:
            if existing.record_hash == transition.transition_hash:
                return await self._required(workspace_id, transition.episode_id)
            raise MarlConflictError("transition identity conflicts with existing content")
        if (
            episode.status is not EpisodeStatus.OPEN
            or episode.pending_boundary != transition.boundary
        ):
            raise MarlConflictError("transition does not close the pending boundary")
        if transition.decision_index != len(episode.transitions):
            raise MarlConflictError("transition index is not gapless")
        self._session.add(
            MarlRecordRow(
                id=transition.post_observation.observation_id,
                workspace_id=workspace_id,
                session_id=episode.session_id,
                episode_id=episode.episode_id,
                decision_index=transition.decision_index,
                record_kind="TRANSITION",
                record_hash=transition.transition_hash,
                payload=_payload(transition),
            )
        )
        await self._flush_conflict("transition persistence conflict")
        return await self._required(workspace_id, transition.episode_id)

    async def finalize_complete(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeV1:
        episode = await self._locked(workspace_id, episode_id)
        if episode.status is EpisodeStatus.COMPLETE:
            return episode
        MarlEpisodeV1.model_validate(
            {**episode.model_dump(mode="python"), "status": EpisodeStatus.COMPLETE}
        )
        row = await self._episode_row(workspace_id, episode_id)
        row.status = EpisodeStatus.COMPLETE.value
        await self._session.flush()
        return await self._required(workspace_id, episode_id)

    async def finalize_incomplete(
        self, workspace_id: UUID, marker: IncompleteMarkerV1
    ) -> MarlEpisodeV1:
        episode = await self._locked(workspace_id, marker.episode_id)
        if episode.status is EpisodeStatus.INCOMPLETE:
            if episode.incomplete_marker == marker:
                return episode
            raise MarlConflictError("incomplete marker conflicts with existing marker")
        MarlEpisodeV1.model_validate(
            {
                **episode.model_dump(mode="python"),
                "status": EpisodeStatus.INCOMPLETE,
                "incomplete_marker": marker,
            }
        )
        row = await self._episode_row(workspace_id, marker.episode_id)
        row.status = EpisodeStatus.INCOMPLETE.value
        row.incomplete_marker = _payload(marker)
        row.incomplete_hash = marker.incomplete_hash
        await self._session.flush()
        return await self._required(workspace_id, marker.episode_id)

    async def _locked(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeV1:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": f"marl:{workspace_id}:{episode_id}"},
        )
        return await self._required(workspace_id, episode_id)

    async def _required(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeV1:
        episode = await self.get(workspace_id, episode_id)
        if episode is None:
            raise MarlDomainError("episode not found")
        return episode

    async def _episode_row(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeRow:
        row = await self._session.scalar(
            select(MarlEpisodeRow).where(
                MarlEpisodeRow.workspace_id == workspace_id, MarlEpisodeRow.id == episode_id
            )
        )
        if row is None:
            raise MarlDomainError("episode not found")
        return row

    async def _record(
        self,
        workspace_id: UUID,
        episode_id: UUID,
        decision_index: int,
        kind: str,
    ) -> MarlRecordRow | None:
        return cast(
            MarlRecordRow | None,
            await self._session.scalar(
                select(MarlRecordRow).where(
                    MarlRecordRow.workspace_id == workspace_id,
                    MarlRecordRow.episode_id == episode_id,
                    MarlRecordRow.decision_index == decision_index,
                    MarlRecordRow.record_kind == kind,
                ),
            ),
        )

    async def _flush_conflict(self, detail: str) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise MarlConflictError(detail) from exc
