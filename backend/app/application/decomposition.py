"""Automatic problem decomposition into validated proposition proposals only."""

from __future__ import annotations

from typing import cast

from app.domain.agent_activity import ProposalBundle
from app.domain.reasoning import (
    ArtifactKind,
    PropositionNormalizationStatus,
    PropositionPayload,
    validate_artifact_payload,
)
from app.ports.agent_runtime import AgentRuntime, ReasoningContext, ReasoningPhase
from app.ports.errors import PermanentPortError

__all__ = ["ProblemDecomposer"]


# trace: FR-103
class ProblemDecomposer:
    """Validate one runtime bundle without allocating identity or committing state."""

    def __init__(self, runtime: AgentRuntime[ProposalBundle]) -> None:
        self._runtime = runtime

    async def decompose(self, context: ReasoningContext) -> ProposalBundle:
        if context.phase is not ReasoningPhase.DECOMPOSE:
            raise ValueError("problem decomposition requires DECOMPOSE context")

        bundle = (await self._runtime.run_turn(context)).proposal
        if not bundle.artifacts:
            raise _invalid("decomposition returned no propositions")
        if bundle.evidence_requests or bundle.simulation_request_refs:
            raise _invalid("decomposition may contain proposition proposals only")

        identities: set[str] = set()
        for proposal in bundle.artifacts:
            if proposal.kind is not ArtifactKind.PROPOSITION:
                raise _invalid("decomposition may contain PROPOSITION artifacts only")
            payload = cast(
                PropositionPayload,
                validate_artifact_payload(ArtifactKind.PROPOSITION, proposal.payload),
            )
            if payload.canonicalizer_version != context.canonicalizer_version:
                raise _invalid("proposition canonicalizer version does not match pinned context")
            if payload.normalization_status is PropositionNormalizationStatus.AMBIGUOUS:
                raise _invalid("AMBIGUOUS proposition normalization cannot be proposed")
            identity = payload.normalization_identity()
            if identity in identities:
                raise _invalid("decomposition contains duplicate proposition meaning")
            identities.add(identity)
        return bundle


def _invalid(message: str) -> PermanentPortError:
    return PermanentPortError(message, port="agent_runtime")
