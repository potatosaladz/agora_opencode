"""Live PostgreSQL proof for the complete deterministic T7-07 handoff read model."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.application.artifact_commit import ArtifactCommitService, ArtifactEventContext
from app.application.critique_response import CritiqueResponseCommand, CritiqueResponseCommitter
from app.db.critique_handoff import SqlAlchemyCritiqueExplanationHandoffReader
from app.db.critique_response import SqlAlchemyCritiqueResponseStore
from app.db.reasoning_artifacts import SqlAlchemyReasoningArtifactStore
from app.db.reasoning_graph import SqlAlchemyReasoningGraphStore
from app.db.reasoning_ledger import SqlAlchemyReasoningLedger
from app.domain.critique import (
    ArtifactRevisionProposal,
    CritiqueResponseDisposition,
    CritiqueResponseProposal,
)
from app.domain.critique_handoff import CritiqueHandoffEmptyReason
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    CritiquePayload,
    CritiqueType,
    GraphEdgeType,
    LifecycleStatus,
    ParentRelationship,
    Provenance,
    ProvenanceOrigin,
    ReasoningArtifact,
    Resolution,
    Severity,
    artifact_content_hash,
    validate_artifact,
)
from app.domain.reasoning_ledger import LedgerAppend
from app.ports.agent_runtime import (
    ContextArtifact,
    PinnedAgentDefinition,
    ReasoningContext,
    ReasoningPhase,
    TurnExecutionResult,
)
from tests.integration.test_reasoning_persistence import (
    _DATABASE_URL,
    TenantFixture,
    _claim_artifact,
    _insert_session_graph,
    _migrated_database,
)
from tests.traceability import req

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL test settings are not configured"),
]


async def _critic_definition(connection: AsyncConnection, fixture: TenantFixture) -> UUID:
    critic_id = uuid4()
    await connection.execute(
        text(
            "INSERT INTO agent_definitions ("
            "id, workspace_id, logical_id, version, name, domain, role_kind, "
            "strategy_ref, strategy_ver, prompt_ref, prompt_hash, status"
            ") VALUES ("
            ":id, :workspace_id, :logical_id, 1, :name, 'testing', 'critic', "
            "'strategies/critic', '1', 'prompts/critic', :prompt_hash, 'ACTIVE'"
            ")"
        ),
        {
            "id": critic_id,
            "workspace_id": fixture.workspace_id,
            "logical_id": uuid4(),
            "name": f"Critic {critic_id.hex}",
            "prompt_hash": "sha256:" + "c" * 64,
        },
    )
    return critic_id


def _critique(
    fixture: TenantFixture,
    *,
    target_id: UUID,
    logical_id: UUID,
    critique_id: UUID,
    critique_type: CritiqueType,
    created_at: datetime,
) -> ReasoningArtifact:
    values: dict[str, object] = {
        "id": critique_id,
        "workspace_id": fixture.workspace_id,
        "session_id": fixture.session_id,
        "logical_id": logical_id,
        "kind": ArtifactKind.CRITIQUE,
        "schema_version": 1,
        "version": 1,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": None,
        "owner_actor_class": ActorClass.AGENT,
        "owner_actor_id": fixture.agent_id,
        "round": 2,
        "payload": CritiquePayload(
            target_id=target_id,
            critique_type=critique_type,
            severity=Severity.HIGH,
            argument="The selected Claim has a material defect.",
            resolution=Resolution.OPEN,
        ),
        "provenance": Provenance(origin=ProvenanceOrigin.LLM, reference="fixture"),
        "source_references": (),
        "parent_relationships": (
            ParentRelationship(edge_type=GraphEdgeType.ATTACKS, target_artifact_id=target_id),
        ),
        "confidence": None,
        "metadata": {},
        "created_at": created_at,
        "updated_at": created_at,
    }
    values["content_hash"] = artifact_content_hash(values)
    return validate_artifact(values)


def _definition(fixture: TenantFixture) -> PinnedAgentDefinition:
    return PinnedAgentDefinition(
        id=fixture.agent_id,
        logical_id=fixture.agent_id,
        version=1,
        name="integration-agent",
        domain="testing",
        role_kind="domain_expert",
        strategy_name="evidence-first",
        strategy_version="1.0.0",
        prompt_ref="prompts/integration/v1.txt",
        prompt_hash="sha256:" + "d" * 64,
    )


def _response(
    fixture: TenantFixture,
    critique: ReasoningArtifact,
    target: ReasoningArtifact,
    *,
    disposition: CritiqueResponseDisposition,
    committed_at: datetime,
    warrant: ReasoningArtifact | None = None,
) -> CritiqueResponseCommand:
    definition = _definition(fixture)
    visible = tuple(value for value in (target, critique, warrant) if value is not None)
    context = ReasoningContext(
        workspace_id=fixture.workspace_id,
        session_id=fixture.session_id,
        agent_definition_id=fixture.agent_id,
        agent_definition_version=1,
        agent_definition=definition,
        strategy_name=definition.strategy_name,
        strategy_version=definition.strategy_version,
        canonicalizer_version="canonicalizer@1",
        turn_id=uuid4(),
        correlation_id=uuid4(),
        causation_id=uuid4(),
        round=3,
        phase=ReasoningPhase.REVISE,
        problem_statement="Address the assigned Critique.",
        visible_artifact_ids=tuple(value.id for value in visible),
        visible_artifacts=tuple(
            ContextArtifact(
                id=value.id,
                kind=value.kind.value,
                owner_actor_class=value.owner_actor_class.value,
                owner_actor_id=value.owner_actor_id,
                round=value.round,
                content_hash=value.content_hash,
                artifact_json=value.model_dump_json(),
            )
            for value in visible
        ),
        sealed=True,
        budget_remaining_tokens=500,
        budget_remaining_usd=Decimal("1"),
        timeout_s=10,
    )
    response_id = uuid4()
    remaining_issue: str | None = None
    warrant_artifact_ids: tuple[UUID, ...] = ()
    proposed_revision: ArtifactRevisionProposal | None = None
    if disposition is CritiqueResponseDisposition.PARTIALLY_ACCEPT:
        remaining_issue = "Evidence is still incomplete."
    elif disposition is CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION:
        assert warrant is not None
        warrant_artifact_ids = (warrant.id,)
    elif disposition is CritiqueResponseDisposition.REVISE:
        proposed_revision = ArtifactRevisionProposal(
            op="propose",
            kind=ArtifactKind.CLAIM,
            payload={
                "statement": "The revised Claim explicitly acknowledges limited evidence.",
                "claim_type": "FACTUAL",
                "direction": "SUPPORTS",
                "strength": "WEAK",
                "supporting_evidence_ids": [],
                "opposing_evidence_ids": [],
                "review_status": "CONTESTED",
            },
        )
    proposal = CritiqueResponseProposal(
        protocol_version="1.0",
        kind="critique_response",
        response_id=response_id,
        workspace_id=fixture.workspace_id,
        session_id=fixture.session_id,
        responding_definition_id=fixture.agent_id,
        responding_definition_version=1,
        turn_id=context.turn_id,
        correlation_id=context.correlation_id,
        causation_id=context.causation_id,
        round=3,
        critique_id=critique.id,
        critique_version=critique.version,
        target_artifact_id=target.id,
        target_artifact_version=target.version,
        disposition=disposition,
        rationale="Deterministic response fixture.",
        remaining_issue=remaining_issue,
        warrant_artifact_ids=warrant_artifact_ids,
        proposed_revision=proposed_revision,
    )
    return CritiqueResponseCommand(
        context=context,
        execution=TurnExecutionResult(
            proposal=proposal,
            provider="mock",
            model="handoff-fixture",
            input_tokens=10,
            output_tokens=5,
            cost_usd=Decimal("0.001"),
            raw_artifact_ref="raw/handoff.json#sha256:" + "e" * 64,
        ),
        committed_at=committed_at,
    )


async def _append_completed_turn(
    session: AsyncSession,
    fixture: TenantFixture,
    *,
    actor_id: UUID,
    phase: ReasoningPhase,
) -> None:
    turn_id = uuid4()
    await SqlAlchemyReasoningLedger(session).append(
        LedgerAppend(
            id=uuid4(),
            workspace_id=fixture.workspace_id,
            session_id=fixture.session_id,
            event_type="AGENT_TURN_COMPLETED",
            payload_schema_version=1,
            correlation_id=uuid4(),
            actor_class=ActorClass.AGENT,
            actor_id=actor_id,
            round=2,
            payload={
                "turn_id": str(turn_id),
                "artifact_ids": [],
                "proposal_count": 0,
                "attribution": {"phase": phase.value},
            },
            recorded_at=datetime(2026, 9, 7, 18, tzinfo=UTC),
        )
    )


async def _commit_artifacts(
    session: AsyncSession,
    fixture: TenantFixture,
    targets: tuple[ReasoningArtifact, ...],
    critiques: tuple[ReasoningArtifact, ...],
) -> None:
    service = ArtifactCommitService(
        SqlAlchemyReasoningArtifactStore(session),
        SqlAlchemyReasoningGraphStore(session),
        SqlAlchemyReasoningLedger(session),
    )
    for target in targets:
        await service.commit(
            target,
            node_id=uuid4(),
            label="Target Claim",
            context=ArtifactEventContext(
                event_id=uuid4(),
                correlation_id=uuid4(),
                actor_class=ActorClass.AGENT,
                actor_id=fixture.agent_id,
                recorded_at=target.created_at,
            ),
        )
    for critique in critiques:
        await service.commit(
            critique,
            node_id=uuid4(),
            relationship_edge_ids=(uuid4(),),
            label="Critique",
            context=ArtifactEventContext(
                event_id=uuid4(),
                correlation_id=uuid4(),
                actor_class=ActorClass.AGENT,
                actor_id=fixture.agent_id,
                recorded_at=critique.created_at,
            ),
        )


@req("FR-504")
async def test_handoff_reads_every_chain_head_in_creation_ledger_order_with_empty_reasons() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "critique-handoff")
            critic_id = await _critic_definition(connection, fixture)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async with sessions.begin() as session:
            reader = SqlAlchemyCritiqueExplanationHandoffReader(session)
            no_run = await reader.read(fixture.workspace_id, fixture.session_id)
        assert no_run.empty_reason is CritiqueHandoffEmptyReason.NO_COMPLETED_CRITIC_RUN

        async with sessions.begin() as session:
            await _append_completed_turn(
                session,
                fixture,
                actor_id=fixture.agent_id,
                phase=ReasoningPhase.CRITIQUE,
            )
        async with sessions.begin() as session:
            peer_only = await SqlAlchemyCritiqueExplanationHandoffReader(session).read(
                fixture.workspace_id, fixture.session_id
            )
        assert peer_only.empty_reason is CritiqueHandoffEmptyReason.NO_COMPLETED_CRITIC_RUN

        async with sessions.begin() as session:
            await _append_completed_turn(
                session,
                fixture,
                actor_id=critic_id,
                phase=ReasoningPhase.CRITIQUE,
            )
        async with sessions.begin() as session:
            empty_run = await SqlAlchemyCritiqueExplanationHandoffReader(session).read(
                fixture.workspace_id, fixture.session_id
            )
        assert (
            empty_run.empty_reason
            is CritiqueHandoffEmptyReason.COMPLETED_CRITIC_RUN_WITHOUT_CRITIQUES
        )

        target_time = datetime(2026, 9, 7, 19, tzinfo=UTC)
        targets = tuple(
            _claim_artifact(
                fixture,
                uuid4(),
                uuid4(),
                statement=f"Target Claim {index}",
                owner_actor_class=ActorClass.AGENT,
                owner_actor_id=fixture.agent_id,
            ).model_copy(update={"created_at": target_time, "updated_at": target_time})
            for index in range(4)
        )
        creation_times = (
            datetime(2026, 9, 7, 23, tzinfo=UTC),
            datetime(2026, 9, 7, 22, tzinfo=UTC),
            datetime(2026, 9, 7, 21, tzinfo=UTC),
            datetime(2026, 9, 7, 20, tzinfo=UTC),
        )
        critiques = tuple(
            _critique(
                fixture,
                target_id=target.id,
                logical_id=uuid4(),
                critique_id=uuid4(),
                critique_type=(
                    CritiqueType.EVIDENCE_GAP if index == 0 else CritiqueType.LOGICAL_FALLACY
                ),
                created_at=creation_times[index],
            )
            for index, target in enumerate(targets)
        )
        warrant = _claim_artifact(
            fixture,
            uuid4(),
            uuid4(),
            statement="Independent warrant Claim",
            owner_actor_class=ActorClass.AGENT,
            owner_actor_id=fixture.agent_id,
        )

        async with sessions.begin() as session:
            await _commit_artifacts(session, fixture, (*targets, warrant), critiques)
        response_specs = (
            (1, CritiqueResponseDisposition.PARTIALLY_ACCEPT, None),
            (2, CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION, warrant),
            (3, CritiqueResponseDisposition.REVISE, None),
        )
        results = []
        async with sessions.begin() as session:
            artifacts = SqlAlchemyReasoningArtifactStore(session)
            graph = SqlAlchemyReasoningGraphStore(session)
            ledger = SqlAlchemyReasoningLedger(session)
            committer = CritiqueResponseCommitter(
                artifacts, graph, ledger, SqlAlchemyCritiqueResponseStore(session)
            )
            for index, disposition, response_warrant in response_specs:
                results.append(
                    await committer.commit(
                        _response(
                            fixture,
                            critiques[index],
                            targets[index],
                            disposition=disposition,
                            committed_at=datetime(2026, 9, 8, index, tzinfo=UTC),
                            warrant=response_warrant,
                        )
                    )
                )

        async with sessions.begin() as session:
            handoff = await SqlAlchemyCritiqueExplanationHandoffReader(session).read(
                fixture.workspace_id, fixture.session_id
            )

        assert handoff.empty_reason is None
        assert tuple(entry.logical_id for entry in handoff.entries) == tuple(
            critique.logical_id for critique in critiques
        )
        assert tuple(entry.version for entry in handoff.entries) == (1, 2, 2, 2)
        assert tuple(entry.resolution for entry in handoff.entries) == (
            Resolution.OPEN,
            Resolution.UNRESOLVED,
            Resolution.DISPUTED,
            Resolution.RESOLVED,
        )
        assert tuple(entry.response_disposition for entry in handoff.entries) == (
            None,
            CritiqueResponseDisposition.PARTIALLY_ACCEPT,
            CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION,
            CritiqueResponseDisposition.REVISE,
        )
        assert handoff.entries[2].warrant_artifact_ids == (warrant.id,)
        assert handoff.entries[3].replacement_target_artifact_id == results[2].target_revision_id
        assert tuple(entry.creation_ledger_seq for entry in handoff.entries) == tuple(
            sorted(entry.creation_ledger_seq for entry in handoff.entries)
        )
