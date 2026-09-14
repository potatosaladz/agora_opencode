"""Deterministic in-memory implementation of the Phase 12 trajectory store."""

from __future__ import annotations

import asyncio
from uuid import UUID

from app.domain.marl import (
    DecisionBoundaryV1,
    EpisodeStatus,
    IncompleteMarkerV1,
    MarlConflictError,
    MarlDomainError,
    MarlEpisodeV1,
    TransitionV1,
    canonical_hash,
)

__all__ = ["InMemoryMarlTrajectoryStore"]


def _identity(value: object) -> str:
    if hasattr(value, "model_dump"):
        model = value
        return canonical_hash(model.model_dump(mode="json"))
    raise TypeError("trajectory value must be a model")


class InMemoryMarlTrajectoryStore:
    """Serialize writers with the same append-or-conflict behavior as PostgreSQL."""

    def __init__(self) -> None:
        self._episodes: dict[tuple[UUID, UUID], MarlEpisodeV1] = {}
        self._lock = asyncio.Lock()

    async def create(self, episode: MarlEpisodeV1) -> MarlEpisodeV1:
        if (
            episode.status is not EpisodeStatus.OPEN
            or episode.transitions
            or episode.pending_boundary
        ):
            raise MarlDomainError("new episode must be empty and OPEN")
        async with self._lock:
            key = (episode.workspace_id, episode.episode_id)
            current = self._episodes.get(key)
            if current is not None:
                if _identity(current) == _identity(episode):
                    return current
                raise MarlConflictError("episode identity conflicts with existing content")
            self._episodes[key] = episode
            return episode

    async def get(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeV1 | None:
        return self._episodes.get((workspace_id, episode_id))

    async def capture(self, workspace_id: UUID, boundary: DecisionBoundaryV1) -> MarlEpisodeV1:
        async with self._lock:
            episode = self._required(workspace_id, boundary.episode_id)
            if episode.status is not EpisodeStatus.OPEN:
                raise MarlConflictError("finalized episode cannot accept a boundary")
            if episode.pending_boundary is not None:
                if _identity(episode.pending_boundary) == _identity(boundary):
                    return episode
                raise MarlConflictError("episode already has a pending boundary")
            if boundary.decision_index != len(episode.transitions):
                raise MarlConflictError("decision index must be the next gapless index")
            updated = episode.model_copy(update={"pending_boundary": boundary})
            self._episodes[(workspace_id, episode.episode_id)] = updated
            return updated

    async def close(self, workspace_id: UUID, transition: TransitionV1) -> MarlEpisodeV1:
        async with self._lock:
            episode = self._required(workspace_id, transition.episode_id)
            if transition.decision_index < len(episode.transitions):
                current = episode.transitions[transition.decision_index]
                if _identity(current) == _identity(transition):
                    return episode
                raise MarlConflictError("transition identity conflicts with existing content")
            if episode.status is not EpisodeStatus.OPEN or episode.pending_boundary is None:
                raise MarlConflictError("episode has no pending decision")
            if _identity(episode.pending_boundary) != _identity(transition.boundary):
                raise MarlConflictError("transition does not close the pending boundary")
            updated = episode.model_copy(
                update={
                    "transitions": (*episode.transitions, transition),
                    "pending_boundary": None,
                }
            )
            self._episodes[(workspace_id, episode.episode_id)] = updated
            return updated

    async def finalize_complete(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeV1:
        async with self._lock:
            episode = self._required(workspace_id, episode_id)
            if episode.status is EpisodeStatus.COMPLETE:
                return episode
            if episode.status is not EpisodeStatus.OPEN:
                raise MarlConflictError("episode is already incomplete")
            updated = MarlEpisodeV1.model_validate(
                {**episode.model_dump(mode="python"), "status": EpisodeStatus.COMPLETE}
            )
            self._episodes[(workspace_id, episode_id)] = updated
            return updated

    async def finalize_incomplete(
        self, workspace_id: UUID, marker: IncompleteMarkerV1
    ) -> MarlEpisodeV1:
        async with self._lock:
            episode = self._required(workspace_id, marker.episode_id)
            if episode.status is EpisodeStatus.INCOMPLETE:
                if episode.incomplete_marker == marker:
                    return episode
                raise MarlConflictError("incomplete marker conflicts with existing marker")
            if episode.status is not EpisodeStatus.OPEN:
                raise MarlConflictError("complete episode cannot become incomplete")
            updated = MarlEpisodeV1.model_validate(
                {
                    **episode.model_dump(mode="python"),
                    "status": EpisodeStatus.INCOMPLETE,
                    "incomplete_marker": marker,
                }
            )
            self._episodes[(workspace_id, episode.episode_id)] = updated
            return updated

    def _required(self, workspace_id: UUID, episode_id: UUID) -> MarlEpisodeV1:
        value = self._episodes.get((workspace_id, episode_id))
        if value is None:
            raise MarlDomainError("episode not found")
        return value
