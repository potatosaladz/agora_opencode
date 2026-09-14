"""Atomic coordinator commit boundary for assigned Phase 7 Critique proposals."""

from __future__ import annotations

from app.application.artifact_commit import ArtifactWriteResult
from app.application.proposal_commit import AgentProposalCommitter, AgentTurnCommit
from app.domain.critique import CritiqueAssignment, validate_critic_bundle
from app.ports.agent_runtime import ReasoningPhase

__all__ = ["CritiqueProposalCommitter"]


# trace: FR-205, FR-501, FR-502
class CritiqueProposalCommitter:
    """Authorize one Critic turn, then reuse the generic atomic proposal committer."""

    def __init__(self, proposals: AgentProposalCommitter) -> None:
        self._proposals = proposals

    async def commit(
        self,
        command: AgentTurnCommit,
        assignment: CritiqueAssignment,
    ) -> tuple[ArtifactWriteResult, ...]:
        context = command.context
        if context.phase is not ReasoningPhase.CRITIQUE:
            raise ValueError("Critique commit requires CRITIQUE phase")
        if context.agent_definition.role_kind not in {"critic", "domain_expert"}:
            raise ValueError("Critique commit requires a critic or domain expert definition")
        if context.sealed:
            raise ValueError("Critique commit requires coordinator-selected public context")
        pins = (
            context.workspace_id,
            context.session_id,
            context.agent_definition_id,
            context.agent_definition_version,
            context.turn_id,
            context.correlation_id,
            context.causation_id,
            context.round,
            context.visible_artifact_ids,
        )
        expected = (
            assignment.workspace_id,
            assignment.session_id,
            assignment.critic_definition_id,
            assignment.critic_definition_version,
            assignment.turn_id,
            assignment.correlation_id,
            assignment.causation_id,
            assignment.round,
            assignment.target_artifact_ids,
        )
        if pins != expected:
            raise ValueError("Critique assignment does not match authorized reasoning context")
        validate_critic_bundle(command.result.bundle, assignment)
        return await self._proposals.commit(command, critique_assignment=assignment)
