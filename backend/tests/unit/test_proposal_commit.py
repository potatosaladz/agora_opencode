"""T6-04 deterministic proposal validation and atomic coordinator-commit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.application.proposal_commit import (
    AgentProposalCommitter,
    AgentTurnCommit,
    agent_turn_commit_id,
)
from app.domain.agent_activity import (
    AgentTurnResult,
    ArtifactProposal,
    EvidenceDisposition,
    ProposalBundle,
)
from app.domain.artifact_commit import ArtifactCommitError
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    Bearing,
    ClaimType,
    Confidence,
    EvidenceProvenance,
    EvidenceRelation,
    LifecycleStatus,
    PositionPayload,
    PropositionNormalizationStatus,
    Provenance,
    ProvenanceOrigin,
    ReasoningArtifact,
    ReviewStatus,
    SourceReference,
    Stance,
    Strength,
    TrustLevel,
    Verification,
    artifact_content_hash,
    validate_artifact,
)
from app.domain.reasoning_graph import GraphEdge, GraphNode
from app.domain.reasoning_ledger import (
    LedgerAppend,
    LedgerEvent,
    LedgerVerification,
    ledger_event_hash,
    ledger_payload_hash,
)
from app.ports.agent_runtime import (
    ContextArtifact,
    PinnedAgentDefinition,
    ReasoningContext,
    ReasoningPhase,
)
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{index:012d}") for index in range(1, 30))
NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


def _context(**changes: object) -> ReasoningContext:
    proposition, evidence = _proposition(), _evidence()
    values: dict[str, object] = {
        "workspace_id": U[0],
        "session_id": U[1],
        "agent_definition_id": U[2],
        "agent_definition_version": 3,
        "agent_definition": PinnedAgentDefinition(
            id=U[2],
            logical_id=U[3],
            version=3,
            name="fiscal-analyst",
            domain="fiscal",
            role_kind="domain_expert",
            strategy_name="evidence-first",
            strategy_version="1.0.0",
            prompt_ref="prompts/fiscal/v3.txt",
            prompt_hash="sha256:" + "a" * 64,
        ),
        "strategy_name": "evidence-first",
        "strategy_version": "1.0.0",
        "canonicalizer_version": "canonicalizer@1",
        "turn_id": U[4],
        "correlation_id": U[5],
        "causation_id": U[6],
        "round": 2,
        "phase": ReasoningPhase.ARGUE,
        "problem_statement": "Choose a fair transport intervention.",
        "visible_artifact_ids": (U[8], U[9]),
        "visible_artifacts": (
            ContextArtifact(
                id=proposition.id,
                kind="PROPOSITION",
                owner_actor_class=proposition.owner_actor_class.value,
                owner_actor_id=proposition.owner_actor_id,
                round=proposition.round,
                content_hash=proposition.content_hash,
                artifact_json=proposition.model_dump_json(),
            ),
            ContextArtifact(
                id=evidence.id,
                kind="EVIDENCE",
                owner_actor_class=evidence.owner_actor_class.value,
                owner_actor_id=evidence.owner_actor_id,
                round=evidence.round,
                content_hash=evidence.content_hash,
                artifact_json=evidence.model_dump_json(),
            ),
        ),
        "sealed": False,
        "budget_remaining_tokens": 900,
        "budget_remaining_usd": Decimal("1.25"),
        "timeout_s": 12.0,
    }
    values.update(changes)
    return ReasoningContext.model_validate(values)


def _persisted(
    kind: ArtifactKind,
    artifact_id: UUID,
    payload: dict[str, object],
    *,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    round_: int = 1,
) -> ReasoningArtifact:
    source_references: tuple[SourceReference, ...] = ()
    if kind is ArtifactKind.EVIDENCE:
        source_references = (
            SourceReference(
                reference="fixture-source",
                locator={"page": 1},
                content_hash="sha256:" + "b" * 64,
                retrieved_at=NOW,
            ),
        )
    values: dict[str, object] = {
        "id": artifact_id,
        "workspace_id": U[0],
        "session_id": U[1],
        "logical_id": artifact_id,
        "kind": kind,
        "schema_version": 1,
        "version": 1,
        "status": status,
        "supersedes_id": None,
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": U[7],
        "round": round_,
        "payload": payload,
        "provenance": Provenance(origin=ProvenanceOrigin.HUMAN, reference="fixture"),
        "source_references": source_references,
        "parent_relationships": (),
        "confidence": None,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    values["content_hash"] = artifact_content_hash(values)
    return validate_artifact(values)


def _proposition(
    artifact_id: UUID = U[8],
    *,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    round_: int = 1,
) -> ReasoningArtifact:
    payload: dict[str, object] = {
        "statement_original": "Should the city price congestion?",
        "statement_normalized": "adopt(congestion_pricing)",
        "canonicalizer_version": "canonicalizer@1",
        "proposition_kind": "EVALUATIVE",
        "modality": "QUESTION",
        "normalization_status": PropositionNormalizationStatus.VALIDATED,
    }
    return _persisted(ArtifactKind.PROPOSITION, artifact_id, payload, status=status, round_=round_)


def _evidence(
    artifact_id: UUID = U[9],
    *,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    round_: int = 1,
) -> ReasoningArtifact:
    payload: dict[str, object] = {
        "claim_id": U[10],
        "relation": EvidenceRelation.SUPPORTS,
        "quote": "Traffic fell after implementation.",
        "verification": Verification.UNVERIFIED,
        "trust_level": TrustLevel.PRIMARY,
        "weight": "0.8",
        "provenance_kind": EvidenceProvenance.HUMAN,
    }
    return _persisted(ArtifactKind.EVIDENCE, artifact_id, payload, status=status, round_=round_)


def _position(
    disposition: EvidenceDisposition = EvidenceDisposition.CITED,
    evidence_ids: tuple[UUID, ...] = (U[9],),
) -> ArtifactProposal:
    return ArtifactProposal(
        op="propose",
        kind=ArtifactKind.POSITION,
        evidence_disposition=disposition,
        confidence=Confidence(
            kind="subjective",
            value="0.70",
            meaning="agent assessment",
            basis_artifact_ids=evidence_ids,
        ),
        payload={
            "target_id": U[8],
            "stance": Stance.CONDITIONALLY_SUPPORT,
            "rationale": "Support with a low-income rebate.",
            "evidence_ids": evidence_ids,
            "conditions": ("Provide a low-income rebate",),
        },
    )


def _snapshot(artifact: ReasoningArtifact) -> ContextArtifact:
    return ContextArtifact(
        id=artifact.id,
        kind=artifact.kind.value,
        owner_actor_class=artifact.owner_actor_class.value,
        owner_actor_id=artifact.owner_actor_id,
        round=artifact.round,
        content_hash=artifact.content_hash,
        artifact_json=artifact.model_dump_json(),
    )


def _claim() -> ArtifactProposal:
    return ArtifactProposal(
        op="propose",
        kind=ArtifactKind.CLAIM,
        payload={
            "statement": "Congestion pricing can reduce peak traffic.",
            "claim_type": "PREDICTIVE",
            "direction": "SUPPORTS",
            "strength": "MODERATE",
            "supporting_evidence_ids": (U[9],),
            "opposing_evidence_ids": (),
            "review_status": "PROPOSED",
        },
    )


def _command(
    *proposals: ArtifactProposal, context: ReasoningContext | None = None
) -> AgentTurnCommit:
    turn = context or _context()
    bundle = ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=turn.turn_id,
        artifacts=proposals,
        self_reported_limits=("No household travel microdata",),
    )
    return AgentTurnCommit(
        context=turn,
        result=AgentTurnResult(
            turn_id=turn.turn_id,
            agent_definition_id=turn.agent_definition_id,
            bundle=bundle,
            provider="mock",
            model="fixture-model",
            input_tokens=120,
            output_tokens=34,
            cost_usd=Decimal("0.0042"),
            raw_artifact_ref="artifacts/turn.json#sha256:" + "c" * 64,
        ),
        committed_at=NOW,
    )


class _Artifacts:
    def __init__(self, *artifacts: ReasoningArtifact) -> None:
        self.values = {artifact.id: artifact for artifact in artifacts}
        self.added: list[ReasoningArtifact] = []
        self.locked: list[UUID] = []

    async def lock_agent_turn(self, workspace_id: UUID, session_id: UUID, turn_id: UUID) -> None:
        assert (workspace_id, session_id, turn_id) == (U[0], U[1], U[4])

    async def add(self, artifact: ReasoningArtifact) -> None:
        self.values[artifact.id] = artifact
        self.added.append(artifact)

    async def get_for_update(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> ReasoningArtifact | None:
        self.locked.append(artifact_id)
        artifact = self.values.get(artifact_id)
        if artifact is None or (artifact.workspace_id, artifact.session_id) != (
            workspace_id,
            session_id,
        ):
            return None
        return artifact

    async def set_lifecycle(
        self,
        workspace_id: UUID,
        session_id: UUID,
        artifact_id: UUID,
        status: LifecycleStatus,
        *,
        updated_at: datetime,
    ) -> None:
        raise AssertionError("proposal commit never changes lifecycle")


class _Graph:
    def __init__(self, *artifacts: ReasoningArtifact) -> None:
        self.nodes = {
            artifact.id: GraphNode(
                id=agent_turn_commit_id(artifact.id, index, "fixture-node"),
                workspace_id=artifact.workspace_id,
                session_id=artifact.session_id,
                kind=artifact.kind,
                ref_id=artifact.id,
                label=artifact.kind.value.title(),
            )
            for index, artifact in enumerate(artifacts)
        }
        self.edges: list[GraphEdge] = []

    async def add_node(self, node: GraphNode) -> None:
        self.nodes[node.ref_id] = node

    async def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        node = self.nodes.get(artifact_id)
        if node is None or (node.workspace_id, node.session_id) != (workspace_id, session_id):
            return None
        return node


class _Ledger:
    def __init__(self, *, fail_at: int | None = None) -> None:
        self.events: list[LedgerEvent] = []
        self.fail_at = fail_at

    async def append(self, event: LedgerAppend) -> LedgerEvent:
        if self.fail_at is not None and len(self.events) == self.fail_at:
            raise RuntimeError("injected ledger failure")
        persisted = LedgerEvent(
            **event.model_dump(),
            ledger_seq=len(self.events) + 1,
            payload_hash=ledger_payload_hash(event.payload),
            prev_hash=self.events[-1].event_hash if self.events else "sha256:" + "0" * 64,
            event_hash="sha256:" + "0" * 64,
        )
        persisted = persisted.model_copy(update={"event_hash": ledger_event_hash(persisted)})
        self.events.append(persisted)
        return persisted

    async def get_by_id(
        self, workspace_id: UUID, session_id: UUID, event_id: UUID
    ) -> LedgerEvent | None:
        return next(
            (
                event
                for event in self.events
                if event.id == event_id
                and (event.workspace_id, event.session_id) == (workspace_id, session_id)
            ),
            None,
        )

    async def read(
        self, workspace_id: UUID, session_id: UUID, *, from_seq: int = 1, limit: int = 1000
    ) -> tuple[LedgerEvent, ...]:
        return tuple(self.events[from_seq - 1 :][:limit])

    async def verify(self, workspace_id: UUID, session_id: UUID) -> LedgerVerification:
        head = self.events[-1].event_hash if self.events else "sha256:" + "0" * 64
        return LedgerVerification(valid=True, event_count=len(self.events), head_hash=head)


@req("FR-210")
async def test_commits_stable_artifact_graph_and_ledger_order_with_full_attribution() -> None:
    proposition, evidence = _proposition(), _evidence()
    artifacts, graph, ledger = (
        _Artifacts(proposition, evidence),
        _Graph(proposition, evidence),
        _Ledger(),
    )
    command = _command(_claim(), _position())

    writes = await AgentProposalCommitter(artifacts, graph, ledger).commit(command)

    assert [write.artifact.kind for write in writes] == [ArtifactKind.CLAIM, ArtifactKind.POSITION]
    assert [write.artifact.id for write in writes] == [
        agent_turn_commit_id(command.context.turn_id, 0, "artifact"),
        agent_turn_commit_id(command.context.turn_id, 1, "artifact"),
    ]
    position = writes[1].artifact
    assert position.metadata["evidence_disposition"] == "CITED"
    attribution = position.metadata["attribution"]
    assert attribution["agent_definition_id"] == str(U[2])
    assert attribution["agent_definition_version"] == 3
    assert attribution["model"] == "fixture-model"
    assert attribution["prompt_hash"] == "sha256:" + "a" * 64
    assert attribution["round"] == 2
    assert attribution["committed_at"] == "2026-09-06T12:00:00Z"
    assert [event.payload["artifact_id"] for event in ledger.events[:2]] == [
        str(writes[0].artifact.id),
        str(writes[1].artifact.id),
    ]
    assert ledger.events[1].payload["evidence_disposition"] == "CITED"
    assert ledger.events[1].payload["attribution"] == attribution
    assert ledger.events[2].event_type == "AGENT_TURN_COMPLETED"
    assert ledger.events[2].payload["artifact_ids"] == tuple(
        str(write.artifact.id) for write in writes
    )
    assert graph.nodes[writes[0].artifact.id].id == agent_turn_commit_id(U[4], 0, "node")
    assert graph.nodes[writes[1].artifact.id].id == agent_turn_commit_id(U[4], 1, "node")


@req("FR-210")
async def test_no_evidence_position_is_explicit_and_commits_without_fake_uuid() -> None:
    proposition = _proposition()
    artifacts, graph, ledger = _Artifacts(proposition), _Graph(proposition), _Ledger()
    proposal = _position(EvidenceDisposition.NO_EVIDENCE, ())

    (write,) = await AgentProposalCommitter(artifacts, graph, ledger).commit(_command(proposal))

    assert cast(PositionPayload, write.artifact.payload).evidence_ids == ()
    assert write.artifact.metadata["evidence_disposition"] == "NO_EVIDENCE"
    assert ledger.events[0].payload["evidence_disposition"] == "NO_EVIDENCE"


@req("FR-210")
async def test_exact_retry_returns_prior_complete_commit_without_duplicate_writes() -> None:
    proposition, evidence = _proposition(), _evidence()
    artifacts, graph, ledger = (
        _Artifacts(proposition, evidence),
        _Graph(proposition, evidence),
        _Ledger(),
    )
    command = _command(_claim(), _position())
    committer = AgentProposalCommitter(artifacts, graph, ledger)

    first = await committer.commit(command)
    retried = await committer.commit(command)

    assert retried == first
    assert len(artifacts.added) == 2
    assert len(graph.nodes) == 4
    assert graph.edges == []
    assert len(ledger.events) == 3


@req("FR-210")
async def test_changed_or_incomplete_prior_turn_commit_fails_closed() -> None:
    proposition, evidence = _proposition(), _evidence()
    artifacts, graph, ledger = (
        _Artifacts(proposition, evidence),
        _Graph(proposition, evidence),
        _Ledger(),
    )
    committer = AgentProposalCommitter(artifacts, graph, ledger)
    await committer.commit(_command(_claim()))

    with pytest.raises(ArtifactCommitError, match="incomplete prior commit"):
        await committer.commit(_command(_claim(), _position()))

    assert len(artifacts.added) == 1
    assert len(ledger.events) == 2

    second_artifacts = _Artifacts(proposition, evidence)
    second_graph, second_ledger = _Graph(proposition, evidence), _Ledger()
    second_committer = AgentProposalCommitter(second_artifacts, second_graph, second_ledger)
    await second_committer.commit(_command(_claim(), _position()))
    with pytest.raises(ArtifactCommitError, match="conflicts with persisted artifact content"):
        await second_committer.commit(_command(_claim()))

    partial_artifacts = _Artifacts(proposition, evidence)
    partial_graph, partial_ledger = _Graph(proposition, evidence), _Ledger()
    prior_event = second_ledger.events[0]
    partial_ledger.events.append(prior_event)
    with pytest.raises(ArtifactCommitError, match="incomplete prior commit"):
        await AgentProposalCommitter(partial_artifacts, partial_graph, partial_ledger).commit(
            _command(_claim())
        )


@req("FR-210")
async def test_existing_but_hidden_reference_fails_before_any_artifact_read_or_write() -> None:
    proposition, evidence = _proposition(), _evidence()
    artifacts, graph, ledger = (
        _Artifacts(proposition, evidence),
        _Graph(proposition, evidence),
        _Ledger(),
    )
    context = _context(
        visible_artifact_ids=(U[8],),
        visible_artifacts=(_context().visible_artifacts[0],),
    )

    with pytest.raises(ArtifactCommitError, match="was not authorized"):
        await AgentProposalCommitter(artifacts, graph, ledger).commit(
            _command(_position(), context=context)
        )

    assert artifacts.locked == [agent_turn_commit_id(U[4], 0, "artifact")]
    assert artifacts.added == []
    assert ledger.events == []


@req("FR-210")
@pytest.mark.parametrize(
    ("references", "message"),
    [
        ((_proposition(),), "does not exist"),
        (
            (
                _proposition(),
                _persisted(
                    ArtifactKind.CLAIM,
                    U[9],
                    {
                        "statement": "Not evidence",
                        "claim_type": ClaimType.FACTUAL,
                        "direction": Bearing.SUPPORTS,
                        "strength": Strength.WEAK,
                        "supporting_evidence_ids": (),
                        "opposing_evidence_ids": (),
                        "review_status": ReviewStatus.PROPOSED,
                    },
                ),
            ),
            "must have kind EVIDENCE",
        ),
        ((_proposition(), _evidence(status=LifecycleStatus.WITHDRAWN)), "not ACTIVE"),
        ((_proposition(), _evidence(round_=3)), "from the future"),
    ],
)
async def test_fabricated_wrong_kind_inactive_or_future_citation_fails_before_any_write(
    references: tuple[ReasoningArtifact, ...], message: str
) -> None:
    artifacts, graph, ledger = _Artifacts(*references), _Graph(*references), _Ledger()

    command = _command(
        _claim(),
        _position(),
        context=_context(
            visible_artifact_ids=tuple(artifact.id for artifact in references),
            visible_artifacts=tuple(_snapshot(artifact) for artifact in references),
        ),
    )
    if message == "does not exist":
        fabricated = ContextArtifact(
            id=U[9],
            kind="EVIDENCE",
            owner_actor_class="HUMAN",
            owner_actor_id=U[7],
            round=1,
            content_hash="sha256:" + "9" * 64,
            artifact_json='{"kind":"EVIDENCE"}',
        )
        command = _command(
            _claim(),
            _position(),
            context=_context(
                visible_artifact_ids=(U[8], U[9]),
                visible_artifacts=(_context().visible_artifacts[0], fabricated),
            ),
        )
    with pytest.raises(ArtifactCommitError, match=message):
        await AgentProposalCommitter(artifacts, graph, ledger).commit(command)

    assert artifacts.added == []
    assert set(graph.nodes) == {artifact.id for artifact in references}
    assert graph.edges == []
    assert ledger.events == []


@req("FR-210")
def test_turn_command_and_retry_stable_identity_fail_closed() -> None:
    command = _command(_claim())
    assert agent_turn_commit_id(U[4], 0, "artifact") == agent_turn_commit_id(U[4], 0, "artifact")
    assert agent_turn_commit_id(U[4], 0, "artifact") != agent_turn_commit_id(U[4], 1, "artifact")
    with pytest.raises(ValueError, match="identity inputs"):
        agent_turn_commit_id(U[4], -1, "artifact")
    with pytest.raises(ValidationError, match="coordinator turn"):
        AgentTurnCommit(
            context=command.context.model_copy(update={"turn_id": U[11]}),
            result=command.result,
            committed_at=NOW,
        )


@req("FR-210")
async def test_caller_transaction_can_roll_back_all_writes_after_injected_mid_bundle_failure() -> (
    None
):
    proposition, evidence = _proposition(), _evidence()
    artifacts, graph, ledger = (
        _Artifacts(proposition, evidence),
        _Graph(proposition, evidence),
        _Ledger(fail_at=1),
    )
    before = (
        artifacts.values.copy(),
        graph.nodes.copy(),
        graph.edges[:],
        ledger.events[:],
    )

    async def execute_in_caller_transaction() -> None:
        try:
            await AgentProposalCommitter(artifacts, graph, ledger).commit(
                _command(_claim(), _position())
            )
        except Exception:
            artifacts.values, graph.nodes, graph.edges, ledger.events = before
            raise

    with pytest.raises(RuntimeError, match="injected ledger failure"):
        await execute_in_caller_transaction()

    assert artifacts.values == before[0]
    assert graph.nodes == before[1]
    assert graph.edges == before[2]
    assert ledger.events == before[3]
