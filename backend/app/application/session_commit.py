"""Atomic construction of a fully bound Phase 3 draft session."""

from __future__ import annotations

from uuid import UUID

from app.application.artifact_commit import ArtifactCommitService, ArtifactEventContext
from app.domain.artifact_commit import ArtifactCommitError
from app.domain.phase3_api import Phase3SessionStore
from app.domain.reasoning import FrozenModel, ReasoningArtifact
from app.domain.reasoning_ledger import LedgerAppend, ReasoningLedger
from app.domain.session_binding import (
    ConstraintBinding,
    DraftSessionBinding,
    ObjectiveBinding,
    SessionBudget,
)
from app.domain.session_lifecycle import SessionLifecycleStore

__all__ = ["SessionArtifactCommit", "SessionCommitService"]


class SessionArtifactCommit(FrozenModel):
    artifact: ReasoningArtifact
    node_id: UUID
    relationship_edge_ids: tuple[UUID, ...] = ()
    label: str
    context: ArtifactEventContext


class SessionCommitService:
    """Commit session, initial artifacts, bindings, and ledger events as one unit."""

    def __init__(
        self,
        sessions: Phase3SessionStore,
        lifecycle: SessionLifecycleStore,
        artifacts: ArtifactCommitService,
        ledger: ReasoningLedger,
    ) -> None:
        self._sessions = sessions
        self._lifecycle = lifecycle
        self._artifacts = artifacts
        self._ledger = ledger

    async def create(
        self,
        *,
        session_id: UUID,
        workspace_id: UUID,
        created_by: UUID,
        problem_statement: str,
        agent_definition_ids: tuple[UUID, ...],
        objective_commits: tuple[SessionArtifactCommit, ...],
        constraint_commits: tuple[SessionArtifactCommit, ...],
        budget: SessionBudget,
        context: ArtifactEventContext,
    ) -> DraftSessionBinding:
        agents = await self._sessions.resolve_agents(workspace_id, session_id, agent_definition_ids)
        if len(agents) != len(agent_definition_ids):
            raise ArtifactCommitError("one or more agent definitions do not exist")
        binding = DraftSessionBinding(
            id=session_id,
            workspace_id=workspace_id,
            problem_statement=problem_statement,
            agents=agents,
            objectives=tuple(
                ObjectiveBinding(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    artifact_id=item.artifact.id,
                )
                for item in objective_commits
            ),
            constraints=tuple(
                ConstraintBinding(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    artifact_id=item.artifact.id,
                )
                for item in constraint_commits
            ),
            budget=budget,
            created_by=created_by,
            created_at=context.recorded_at,
            updated_at=context.recorded_at,
        )
        await self._sessions.add(binding)
        await self._lifecycle.add_draft(workspace_id, session_id, created_at=context.recorded_at)
        await self._ledger.append(
            LedgerAppend(
                id=context.event_id,
                workspace_id=workspace_id,
                session_id=session_id,
                event_type="SESSION_CREATED",
                payload_schema_version=1,
                causation_id=context.causation_id,
                correlation_id=context.correlation_id,
                actor_class=context.actor_class,
                actor_id=context.actor_id,
                round=0,
                payload={
                    "session_id": str(session_id),
                    "objective_ids": [str(item.artifact.id) for item in objective_commits],
                    "constraint_ids": [str(item.artifact.id) for item in constraint_commits],
                },
                recorded_at=context.recorded_at,
            )
        )
        for item in (*objective_commits, *constraint_commits):
            await self._artifacts.commit(
                item.artifact,
                node_id=item.node_id,
                relationship_edge_ids=item.relationship_edge_ids,
                label=item.label,
                context=item.context,
            )
        await self._sessions.bind_artifacts(binding)
        return binding
