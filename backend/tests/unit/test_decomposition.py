"""T6-02 automatic structured problem-decomposition tests."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from app.adapters.inmemory.reasoning_strategy import DeterministicReasoningStrategy
from app.application.agent_runtime import StatelessAgentRuntime, StrategyRegistry
from app.application.decomposition import ProblemDecomposer
from app.domain.agent_activity import ArtifactProposal, ProposalBundle
from app.domain.reasoning import (
    ArtifactKind,
    Bearing,
    ClaimType,
    PropositionNormalizationStatus,
    ReviewStatus,
    Strength,
)
from app.ports.agent_runtime import PinnedAgentDefinition, ReasoningContext, ReasoningPhase
from app.ports.errors import PermanentPortError
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 10))


def context(**changes: object) -> ReasoningContext:
    values: dict[str, object] = {
        "workspace_id": U[0],
        "session_id": U[1],
        "agent_definition_id": U[2],
        "agent_definition_version": 2,
        "agent_definition": PinnedAgentDefinition(
            id=U[2],
            logical_id=U[6],
            version=2,
            name="problem-decomposer",
            domain="policy",
            role_kind="orchestrator",
            strategy_name="structured-decomposition",
            strategy_version="1.0.0",
            prompt_ref="prompts/problem-decomposer/v2.txt",
            prompt_hash="sha256:" + "a" * 64,
        ),
        "strategy_name": "structured-decomposition",
        "strategy_version": "1.0.0",
        "canonicalizer_version": "canonicalizer@1",
        "turn_id": U[3],
        "correlation_id": U[4],
        "causation_id": U[5],
        "round": 1,
        "phase": ReasoningPhase.DECOMPOSE,
        "problem_statement": "How should a city reduce transport emissions fairly?",
        "objective_summaries": ("Reduce emissions", "Protect low-income commuters"),
        "constraint_summaries": ("Annual cost must stay below the approved ceiling",),
        "sealed": False,
        "budget_remaining_tokens": 1200,
        "budget_remaining_usd": Decimal("2.00"),
        "timeout_s": 20.0,
    }
    values.update(changes)
    return ReasoningContext.model_validate(values)


def proposition(
    statement_original: str,
    statement_normalized: str,
    *,
    canonicalizer_version: str = "canonicalizer@1",
    status: PropositionNormalizationStatus = PropositionNormalizationStatus.PROPOSED,
) -> ArtifactProposal:
    return ArtifactProposal(
        op="propose",
        kind=ArtifactKind.PROPOSITION,
        payload={
            "statement_original": statement_original,
            "statement_normalized": statement_normalized,
            "canonicalizer_version": canonicalizer_version,
            "proposition_kind": "EVALUATIVE",
            "modality": "QUESTION",
            "normalization_status": status,
        },
    )


def bundle(*artifacts: ArtifactProposal, evidence_requests: tuple[str, ...] = ()) -> ProposalBundle:
    return ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=U[3],
        artifacts=artifacts,
        evidence_requests=evidence_requests,
        self_reported_limits=("No local travel survey available",),
    )


def decomposer(output: ProposalBundle) -> ProblemDecomposer:
    strategy = DeterministicReasoningStrategy(
        "structured-decomposition", "1.0.0", lambda _context: output
    )
    return ProblemDecomposer(StatelessAgentRuntime(StrategyRegistry((strategy,))))


@req("FR-103")
async def test_decomposition_returns_only_unique_pinned_structured_propositions() -> None:
    output = bundle(
        proposition("Which options cut emissions?", "rank(options,emissions_delta)"),
        proposition("Who bears each option's cost?", "distribution(cost,household_income_band)"),
    )

    result = await decomposer(output).decompose(context())

    assert result is output
    assert [artifact.kind for artifact in result.artifacts] == [
        ArtifactKind.PROPOSITION,
        ArtifactKind.PROPOSITION,
    ]


@req("FR-103")
@pytest.mark.parametrize(
    ("output", "message"),
    [
        (bundle(), "no propositions"),
        (
            bundle(
                ArtifactProposal(
                    op="propose",
                    kind=ArtifactKind.CLAIM,
                    payload={
                        "statement": "Use congestion charging",
                        "claim_type": ClaimType.PROCEDURAL,
                        "direction": Bearing.SUPPORTS,
                        "strength": Strength.MODERATE,
                        "supporting_evidence_ids": (),
                        "opposing_evidence_ids": (),
                        "review_status": ReviewStatus.PROPOSED,
                    },
                )
            ),
            "PROPOSITION artifacts only",
        ),
        (
            bundle(proposition("Question", "question"), evidence_requests=("search",)),
            "proposition proposals only",
        ),
        (
            bundle(proposition("Question", "question", canonicalizer_version="canonicalizer@2")),
            "does not match pinned context",
        ),
        (
            bundle(
                proposition(
                    "Ambiguous question",
                    "ambiguous(question)",
                    status=PropositionNormalizationStatus.AMBIGUOUS,
                )
            ),
            "AMBIGUOUS",
        ),
        (
            bundle(
                proposition("Question one", "same(question)"),
                proposition("Rephrased question", "same(question)"),
            ),
            "duplicate proposition meaning",
        ),
    ],
)
async def test_decomposition_rejects_empty_mixed_requested_unpinned_ambiguous_or_duplicate_output(
    output: ProposalBundle, message: str
) -> None:
    with pytest.raises(PermanentPortError, match=message):
        await decomposer(output).decompose(context())


@req("FR-103")
async def test_decomposition_requires_explicit_decompose_phase() -> None:
    service = decomposer(bundle(proposition("Question", "question")))

    with pytest.raises(ValueError, match="DECOMPOSE context"):
        await service.decompose(context(phase=ReasoningPhase.ARGUE))
