"""PostgreSQL acceptance evidence for tenant-safe Phase 3 reasoning persistence."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from urllib.parse import quote_plus
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.adapters.nats.event_bus import NatsJetStreamEventBus
from app.application.artifact_commit import (
    ArtifactCommitService,
    ArtifactEventContext,
    ArtifactWriteResult,
)
from app.application.critique_response import (
    CritiqueResponseCommand,
    CritiqueResponseCommitter,
    response_commit_id,
)
from app.application.proposal_commit import (
    AgentProposalCommitter,
    AgentTurnCommit,
    agent_turn_commit_id,
)
from app.db import Database
from app.db.coordinator_policy import SqlAlchemyCoordinatorPolicyStore
from app.db.critique_response import SqlAlchemyCritiqueResponseStore
from app.db.phase3_api import SqlAlchemyIdempotencyStore
from app.db.realtime import RealtimeGateway
from app.db.reasoning_artifacts import SqlAlchemyReasoningArtifactStore
from app.db.reasoning_graph import SqlAlchemyReasoningGraphStore
from app.db.reasoning_ledger import SqlAlchemyReasoningLedger
from app.db.session_bootstrap import SqlAlchemySessionTransitionCommitter
from app.db.session_lifecycle import SqlAlchemySessionLifecycleStore
from app.domain import (
    ActorClass,
    ArtifactKind,
    Bearing,
    ClaimPayload,
    ClaimType,
    Confidence,
    CritiquePayload,
    CritiqueType,
    GraphEdgeType,
    GraphNode,
    LedgerAppend,
    LedgerIntegrityError,
    LifecycleStatus,
    ParentRelationship,
    PropositionNormalizationStatus,
    PropositionPayload,
    Provenance,
    ProvenanceOrigin,
    ReasoningArtifact,
    Resolution,
    ReviewStatus,
    Severity,
    Strength,
    artifact_content_hash,
    validate_artifact,
)
from app.domain.agent_activity import (
    AgentTurnResult,
    ArtifactProposal,
    EvidenceDisposition,
    ProposalBundle,
)
from app.domain.artifact_commit import ArtifactCommitError
from app.domain.coordinator_policy import MembershipIntervention, MembershipInterventionKind
from app.domain.critique import (
    ArtifactRevisionProposal,
    CritiqueResponseDisposition,
    CritiqueResponseProposal,
    CritiqueResponseResult,
)
from app.domain.phase3_api import IdempotencyRecord
from app.domain.session_bootstrap import SessionBootstrapTransition
from app.domain.session_lifecycle import SessionLifecycleState, SessionTransition
from app.ports.agent_runtime import (
    ContextArtifact,
    PinnedAgentDefinition,
    ReasoningContext,
    ReasoningPhase,
    TurnExecutionResult,
)
from tests.traceability import req


def _agent_turn_commit(
    fixture: TenantFixture,
    target_id: UUID,
    *,
    turn_id: UUID,
    target_content_hash: str = "sha256:" + "f" * 64,
) -> AgentTurnCommit:
    context = ReasoningContext(
        workspace_id=fixture.workspace_id,
        session_id=fixture.session_id,
        agent_definition_id=fixture.agent_id,
        agent_definition_version=1,
        agent_definition=PinnedAgentDefinition(
            id=fixture.agent_id,
            logical_id=fixture.agent_id,
            version=1,
            name="integration-agent",
            domain="transport",
            role_kind="domain_expert",
            strategy_name="evidence-first",
            strategy_version="1.0.0",
            prompt_ref="prompts/integration/v1.txt",
            prompt_hash="sha256:" + "d" * 64,
        ),
        strategy_name="evidence-first",
        strategy_version="1.0.0",
        canonicalizer_version="canonicalizer@1",
        turn_id=turn_id,
        correlation_id=uuid4(),
        causation_id=uuid4(),
        round=2,
        phase=ReasoningPhase.ARGUE,
        problem_statement="Choose a transport intervention.",
        visible_artifact_ids=(target_id,),
        visible_artifacts=(
            ContextArtifact(
                id=target_id,
                kind="PROPOSITION",
                owner_actor_class="HUMAN",
                owner_actor_id=fixture.user_id,
                round=1,
                content_hash=target_content_hash,
                artifact_json='{"kind":"PROPOSITION"}',
            ),
        ),
        sealed=False,
        budget_remaining_tokens=500,
        budget_remaining_usd=Decimal("1.00"),
        timeout_s=10.0,
    )
    proposal = ArtifactProposal(
        op="propose",
        kind=ArtifactKind.POSITION,
        evidence_disposition=EvidenceDisposition.NO_EVIDENCE,
        confidence=Confidence(
            kind="subjective",
            value="0.55",
            meaning="limited evidence",
            basis_artifact_ids=(),
        ),
        payload={
            "target_id": target_id,
            "stance": "INSUFFICIENT_EVIDENCE",
            "rationale": "No eligible evidence was available.",
            "evidence_ids": (),
            "conditions": (),
        },
    )
    bundle = ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=turn_id,
        artifacts=(proposal,),
        self_reported_limits=("No eligible evidence",),
    )
    return AgentTurnCommit(
        context=context,
        result=AgentTurnResult(
            turn_id=turn_id,
            agent_definition_id=fixture.agent_id,
            bundle=bundle,
            provider="mock",
            model="integration-model",
            input_tokens=20,
            output_tokens=10,
            cost_usd=Decimal("0.001"),
            raw_artifact_ref="raw/integration.json#sha256:" + "e" * 64,
        ),
        committed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
    )


_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DATA_MODEL = _BACKEND_ROOT.parent / "docs" / "DATA_MODEL.md"
_SCHEMA_MANIFEST_START = "<!-- phase3-schema-manifest:start -->"
_SCHEMA_MANIFEST_END = "<!-- phase3-schema-manifest:end -->"
_PHASE_3_REVISIONS = (
    "20260905_0005",
    "20260905_0006",
    "20260905_0007",
    "20260905_0008",
)
SchemaManifest = dict[str, dict[str, dict[str, str]]]


def _load_phase3_schema_manifest() -> SchemaManifest:
    document = _DATA_MODEL.read_text(encoding="utf-8")
    _, start_separator, remainder = document.partition(_SCHEMA_MANIFEST_START)
    block, end_separator, _ = remainder.partition(_SCHEMA_MANIFEST_END)
    assert start_separator, "DATA_MODEL Phase 3 schema manifest start marker is missing"
    assert end_separator, "DATA_MODEL Phase 3 schema manifest end marker is missing"
    _, json_separator, fenced_json = block.partition("```json")
    payload, fence_separator, _ = fenced_json.partition("```")
    assert json_separator, "DATA_MODEL Phase 3 schema manifest JSON fence is missing"
    assert fence_separator, "DATA_MODEL Phase 3 schema manifest closing fence is missing"
    manifest = cast(SchemaManifest, json.loads(payload))
    assert tuple(manifest) == _PHASE_3_REVISIONS
    return manifest


_PHASE_3_SCHEMA = _load_phase3_schema_manifest()
_PHASE_3_TABLES = tuple(_PHASE_3_SCHEMA["20260905_0005"])
_GRAPH_TABLES = tuple(_PHASE_3_SCHEMA["20260905_0006"])
_LEDGER_TABLES = tuple(_PHASE_3_SCHEMA["20260905_0007"])
_API_TABLES = tuple(_PHASE_3_SCHEMA["20260905_0008"])
_PHASE_4_TABLES = ("session_lifecycles",)
_PHASE_5_TABLES = (
    "knowledge_namespaces",
    "knowledge_namespace_grants",
    "sources",
    "documents",
    "chunks",
    "knowledge_ingestion_operations",
    "retrieval_attempts",
    "evidence_citations",
    "source_retractions",
    "semantic_memory_entries",
    "memory_promotions",
    "memory_promotion_evidence",
    "memory_lifecycle_events",
)
_PHASE_6_TABLES = ("session_agent_interventions",)
_PHASE_7_TABLES = ("critique_response_requests", "critique_response_results")
_PHASE_8_TABLES = ("simulation_runs", "simulation_results")
_PHASE_10_TABLES = (
    "consensus_results",
    "consensus_explanations",
    "recommendations",
    "impact_reports",
    "impact_report_dependencies",
    "workspace_event_outbox",
)
_PHASE_11_TABLES = (
    "formalizations",
    "formalization_validations",
    "formalization_decisions",
    "symbolic_evaluations",
)
_PHASE_12_TABLES = ("marl_episodes", "marl_trajectory_records")
_PHASE_13_TABLES = ("access_log", "audit_anchors")
_ALL_PHASE_3_TABLES = tuple(
    table for revision in _PHASE_3_REVISIONS for table in _PHASE_3_SCHEMA[revision]
)


def _database_url() -> str | None:
    configured = os.getenv("TEST_DATABASE_URL")
    if configured:
        return configured
    host = os.getenv("POSTGRES_HOST")
    password = os.getenv("POSTGRES_PASSWORD")
    if not host or password is None:
        return None
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "agora")
    user = os.getenv("POSTGRES_USER", "agora")
    return (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{database}"
    )


_DATABASE_URL = _database_url()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL test settings are not configured"),
]


def _alembic_config() -> Config:
    assert _DATABASE_URL is not None
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    return config


@asynccontextmanager
async def _migrated_database() -> AsyncIterator[AsyncEngine]:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")
    try:
        yield engine
    finally:
        await engine.dispose()


@dataclass(frozen=True)
class TenantFixture:
    workspace_id: UUID
    user_id: UUID
    agent_id: UUID
    session_id: UUID
    objective_id: UUID
    objective_logical_id: UUID
    constraint_id: UUID


def _ledger_append(fixture: TenantFixture, event_id: UUID, label: str) -> LedgerAppend:
    return LedgerAppend(
        id=event_id,
        workspace_id=fixture.workspace_id,
        session_id=fixture.session_id,
        event_type="ARTIFACT_COMMITTED",
        payload_schema_version=1,
        causation_id=None,
        correlation_id=uuid4(),
        actor_class=ActorClass.HUMAN,
        actor_id=fixture.user_id,
        round=0,
        payload={"label": label, "artifact_id": str(fixture.objective_id)},
        recorded_at=datetime(2026, 9, 5, tzinfo=UTC),
    )


def _claim_artifact(
    fixture: TenantFixture,
    artifact_id: UUID,
    logical_id: UUID,
    *,
    version: int = 1,
    supersedes_id: UUID | None = None,
    statement: str = "Atomic claim",
    parent_relationships: tuple[ParentRelationship, ...] = (),
    owner_actor_class: ActorClass = ActorClass.HUMAN,
    owner_actor_id: UUID | None = None,
) -> ReasoningArtifact:
    now = datetime(2026, 9, 5, 15, tzinfo=UTC)
    values: dict[str, object] = {
        "id": artifact_id,
        "workspace_id": fixture.workspace_id,
        "session_id": fixture.session_id,
        "logical_id": logical_id,
        "kind": ArtifactKind.CLAIM,
        "schema_version": 1,
        "version": version,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": supersedes_id,
        "owner_actor_class": owner_actor_class,
        "owner_actor_id": owner_actor_id or fixture.user_id,
        "round": 0,
        "payload": ClaimPayload(
            statement=statement,
            claim_type=ClaimType.FACTUAL,
            direction=Bearing.SUPPORTS,
            strength=Strength.MODERATE,
            supporting_evidence_ids=(),
            opposing_evidence_ids=(),
            review_status=ReviewStatus.PROPOSED,
        ),
        "provenance": Provenance(origin=ProvenanceOrigin.HUMAN, reference="integration-test"),
        "source_references": (),
        "parent_relationships": parent_relationships,
        "confidence": None,
        "metadata": {},
        "created_at": now,
        "updated_at": now,
    }
    values["content_hash"] = artifact_content_hash(values)
    return validate_artifact(values)


def _proposition_artifact(
    fixture: TenantFixture, artifact_id: UUID, logical_id: UUID
) -> ReasoningArtifact:
    now = datetime(2026, 9, 6, 11, tzinfo=UTC)
    values: dict[str, object] = {
        "id": artifact_id,
        "workspace_id": fixture.workspace_id,
        "session_id": fixture.session_id,
        "logical_id": logical_id,
        "kind": ArtifactKind.PROPOSITION,
        "schema_version": 1,
        "version": 1,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": None,
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": fixture.user_id,
        "round": 1,
        "payload": PropositionPayload(
            statement_original="Should the city price congestion?",
            statement_normalized="adopt(congestion_pricing)",
            canonicalizer_version="canonicalizer@1",
            proposition_kind="EVALUATIVE",
            modality="QUESTION",
            normalization_status=PropositionNormalizationStatus.VALIDATED,
        ),
        "provenance": Provenance(origin=ProvenanceOrigin.HUMAN, reference="integration-test"),
        "source_references": (),
        "parent_relationships": (),
        "confidence": None,
        "metadata": {},
        "created_at": now,
        "updated_at": now,
    }
    values["content_hash"] = artifact_content_hash(values)
    return validate_artifact(values)


def _artifact_context(fixture: TenantFixture, event_id: UUID) -> ArtifactEventContext:
    return ArtifactEventContext(
        event_id=event_id,
        correlation_id=uuid4(),
        actor_class=ActorClass.HUMAN,
        actor_id=fixture.user_id,
        recorded_at=datetime(2026, 9, 5, 15, tzinfo=UTC),
    )


async def _insert_tenant(connection: AsyncConnection, label: str) -> tuple[UUID, UUID, UUID]:
    workspace_id, user_id, agent_id = uuid4(), uuid4(), uuid4()
    await connection.execute(
        text("INSERT INTO workspaces (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": workspace_id, "slug": f"t303-{label}-{workspace_id.hex}", "name": label},
    )
    await connection.execute(
        text(
            "INSERT INTO users (id, oidc_issuer, oidc_subject, display_name) "
            "VALUES (:id, 'https://idp.example', :subject, :name)"
        ),
        {"id": user_id, "subject": f"t303-{user_id.hex}", "name": label},
    )
    await connection.execute(
        text(
            "INSERT INTO workspace_members (workspace_id, user_id, role) "
            "VALUES (:workspace_id, :user_id, 'ADMIN')"
        ),
        {"workspace_id": workspace_id, "user_id": user_id},
    )
    await connection.execute(
        text(
            "INSERT INTO agent_definitions ("
            "id, workspace_id, logical_id, version, name, domain, role_kind, "
            "strategy_ref, strategy_ver, prompt_ref, prompt_hash, status"
            ") VALUES ("
            ":id, :workspace_id, :logical_id, 1, :name, 'testing', 'domain_expert', "
            "'strategies/test', '1', 'prompts/test', 'sha256:test', 'ACTIVE'"
            ")"
        ),
        {
            "id": agent_id,
            "workspace_id": workspace_id,
            "logical_id": uuid4(),
            "name": f"Test agent {agent_id.hex}",
        },
    )
    return workspace_id, user_id, agent_id


def _objective_payload(name: str = "Minimize total cost") -> dict[str, object]:
    return {
        "name": name,
        "objective_type": "UTILITY",
        "direction": "MINIMIZE",
        "weight": "1",
        "weight_rationale": "Primary test objective",
        "time_horizon": "one year",
        "conflicts_with_ids": [],
    }


def _constraint_payload() -> dict[str, object]:
    return {
        "name": "Budget ceiling",
        "statement": "Cost must remain within budget",
        "constraint_type": "HARD",
        "category": "budget",
        "evaluation_expression": {
            "language": "agora-expression-v1",
            "ast": {"operator": "lte", "left": "cost", "right": "budget"},
        },
        "formal_status": "VALIDATED",
    }


async def _insert_artifact(
    connection: AsyncConnection,
    *,
    workspace_id: UUID,
    session_id: UUID,
    owner_id: UUID,
    kind: str,
    payload: dict[str, object],
    artifact_id: UUID | None = None,
    logical_id: UUID | None = None,
    version: int = 1,
    supersedes_id: UUID | None = None,
    source_references: list[dict[str, object]] | None = None,
    parent_relationships: list[dict[str, object]] | None = None,
) -> tuple[UUID, UUID]:
    artifact_id = artifact_id or uuid4()
    logical_id = logical_id or uuid4()
    await connection.execute(
        text(
            "INSERT INTO reasoning_artifacts ("
            "id, workspace_id, session_id, logical_id, kind, schema_version, version, status, "
            "supersedes_id, owner_actor_class, owner_actor_id, round, payload, provenance, "
            "source_references, parent_relationships, confidence, metadata, content_hash, "
            "created_at, updated_at"
            ") VALUES ("
            ":id, :workspace_id, :session_id, :logical_id, :kind, 1, :version, 'ACTIVE', "
            ":supersedes_id, 'HUMAN', :owner_id, 0, CAST(:payload AS jsonb), "
            "CAST(:provenance AS jsonb), CAST(:source_references AS jsonb), "
            "CAST(:parent_relationships AS jsonb), NULL, '{}'::jsonb, :content_hash, now(), now()"
            ")"
        ),
        {
            "id": artifact_id,
            "workspace_id": workspace_id,
            "session_id": session_id,
            "logical_id": logical_id,
            "kind": kind,
            "version": version,
            "supersedes_id": supersedes_id,
            "owner_id": owner_id,
            "payload": json.dumps(payload),
            "provenance": json.dumps({"origin": "HUMAN", "reference": "integration-test"}),
            "source_references": json.dumps(source_references or []),
            "parent_relationships": json.dumps(parent_relationships or []),
            "content_hash": f"sha256:{artifact_id.hex * 2}",
        },
    )
    return artifact_id, logical_id


async def _insert_session_graph(connection: AsyncConnection, label: str) -> TenantFixture:
    workspace_id, user_id, agent_id = await _insert_tenant(connection, label)
    session_id = uuid4()
    await connection.execute(
        text(
            "INSERT INTO sessions ("
            "id, workspace_id, problem_statement, max_rounds, budget_tokens, budget_usd, created_by"
            ") VALUES (:id, :workspace_id, :problem, 4, 10000, 25.00, :created_by)"
        ),
        {
            "id": session_id,
            "workspace_id": workspace_id,
            "problem": f"Choose the best option for {label}",
            "created_by": user_id,
        },
    )
    objective_id, objective_logical_id = await _insert_artifact(
        connection,
        workspace_id=workspace_id,
        session_id=session_id,
        owner_id=user_id,
        kind="OBJECTIVE",
        payload=_objective_payload(),
    )
    constraint_id, _ = await _insert_artifact(
        connection,
        workspace_id=workspace_id,
        session_id=session_id,
        owner_id=user_id,
        kind="CONSTRAINT",
        payload=_constraint_payload(),
    )
    await connection.execute(
        text(
            "INSERT INTO session_agents (workspace_id, session_id, agent_def_id) "
            "VALUES (:workspace_id, :session_id, :agent_id)"
        ),
        {"workspace_id": workspace_id, "session_id": session_id, "agent_id": agent_id},
    )
    await connection.execute(
        text(
            "INSERT INTO session_objectives (workspace_id, session_id, artifact_id) "
            "VALUES (:workspace_id, :session_id, :artifact_id)"
        ),
        {"workspace_id": workspace_id, "session_id": session_id, "artifact_id": objective_id},
    )
    await connection.execute(
        text(
            "INSERT INTO session_constraints (workspace_id, session_id, artifact_id) "
            "VALUES (:workspace_id, :session_id, :artifact_id)"
        ),
        {"workspace_id": workspace_id, "session_id": session_id, "artifact_id": constraint_id},
    )
    return TenantFixture(
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=agent_id,
        session_id=session_id,
        objective_id=objective_id,
        objective_logical_id=objective_logical_id,
        constraint_id=constraint_id,
    )


async def _insert_graph_node(
    connection: AsyncConnection,
    fixture: TenantFixture,
    *,
    ref_id: UUID,
    kind: str,
    node_id: UUID | None = None,
) -> UUID:
    node_id = node_id or uuid4()
    await connection.execute(
        text(
            "INSERT INTO graph_nodes "
            "(id, workspace_id, session_id, kind, ref_id, label) "
            "VALUES (:id, :workspace_id, :session_id, :kind, :ref_id, :label)"
        ),
        {
            "id": node_id,
            "workspace_id": fixture.workspace_id,
            "session_id": fixture.session_id,
            "kind": kind,
            "ref_id": ref_id,
            "label": f"{kind} node",
        },
    )
    return node_id


async def _insert_graph_edge(
    connection: AsyncConnection,
    fixture: TenantFixture,
    *,
    from_node: UUID,
    to_node: UUID,
    edge_type: str,
) -> UUID:
    edge_id = uuid4()
    await connection.execute(
        text(
            "INSERT INTO graph_edges ("
            "id, workspace_id, session_id, from_node, to_node, edge_type, actor_class, actor_id"
            ") VALUES ("
            ":id, :workspace_id, :session_id, :from_node, :to_node, :edge_type, "
            "'HUMAN', :actor_id)"
        ),
        {
            "id": edge_id,
            "workspace_id": fixture.workspace_id,
            "session_id": fixture.session_id,
            "from_node": from_node,
            "to_node": to_node,
            "edge_type": edge_type,
            "actor_id": fixture.user_id,
        },
    )
    return edge_id


async def _insert_duplicate_graph_edges(
    engine: AsyncEngine,
    fixture: TenantFixture,
    *,
    from_node: UUID,
    to_node: UUID,
) -> None:
    async with engine.begin() as connection:
        for _ in range(2):
            await _insert_graph_edge(
                connection,
                fixture,
                from_node=from_node,
                to_node=to_node,
                edge_type="CONSTRAINS",
            )


async def _insert_graph_node_and_validate(
    engine: AsyncEngine,
    fixture: TenantFixture,
    *,
    ref_id: UUID,
    kind: str,
) -> None:
    async with engine.begin() as connection:
        await _insert_graph_node(connection, fixture, ref_id=ref_id, kind=kind)
        await connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


async def _append_then_rollback(
    sessions: async_sessionmaker[AsyncSession], fixture: TenantFixture, event_id: UUID
) -> None:
    async with sessions.begin() as session:
        rolled_back = await SqlAlchemyReasoningLedger(session).append(
            _ledger_append(fixture, event_id, "rolled-back")
        )
        assert rolled_back.ledger_seq == 2
        raise RuntimeError("force rollback")


async def _insert_graph_edge_and_validate(
    engine: AsyncEngine,
    fixture: TenantFixture,
    *,
    from_node: UUID,
    to_node: UUID,
    edge_type: str,
) -> None:
    async with engine.begin() as connection:
        await _insert_graph_edge(
            connection,
            fixture,
            from_node=from_node,
            to_node=to_node,
            edge_type=edge_type,
        )
        await connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


async def _update_graph_node_kind_and_validate(
    engine: AsyncEngine, *, node_id: UUID, ref_id: UUID, kind: str
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE graph_nodes SET ref_id = :ref_id, kind = :kind WHERE id = :id"),
            {"ref_id": ref_id, "kind": kind, "id": node_id},
        )
        await connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


async def _insert_graph_node_as_role(
    engine: AsyncEngine,
    *,
    role: str,
    current_workspace_id: UUID,
    fixture: TenantFixture,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"SET ROLE {role}"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(current_workspace_id)},
        )
        await connection.execute(
            text(
                "INSERT INTO graph_nodes "
                "(id, workspace_id, session_id, kind, ref_id, label) "
                "VALUES (:id, :workspace_id, :session_id, 'OBJECTIVE', :ref_id, 'foreign')"
            ),
            {
                "id": uuid4(),
                "workspace_id": fixture.workspace_id,
                "session_id": fixture.session_id,
                "ref_id": fixture.objective_id,
            },
        )


async def _insert_idempotency_as_role(
    engine: AsyncEngine,
    *,
    role: str,
    current_workspace_id: UUID,
    row_workspace_id: UUID,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"SET ROLE {role}"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(current_workspace_id)},
        )
        await connection.execute(
            text(
                "INSERT INTO api_idempotency_records "
                "(workspace_id, operation, key, request_hash, status_code, response_body) "
                "VALUES (:workspace_id, 'session:create', 'foreign', :hash, 201, '{}'::jsonb)"
            ),
            {"workspace_id": row_workspace_id, "hash": f"sha256:{'b' * 64}"},
        )


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_graph_store_keeps_artifact_projection_writes_atomic() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "graph-atomic")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        committed_artifact_id, committed_node_id = uuid4(), uuid4()
        async with sessions.begin() as session:
            await session.execute(
                text(
                    "INSERT INTO reasoning_artifacts ("
                    "id, workspace_id, session_id, logical_id, kind, schema_version, version, "
                    "status, owner_actor_class, owner_actor_id, round, payload, provenance, "
                    "source_references, parent_relationships, metadata, content_hash, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":id, :workspace_id, :session_id, :logical_id, 'ALTERNATIVE', 1, 1, "
                    "'ACTIVE', 'HUMAN', :owner_id, 0, CAST(:payload AS jsonb), "
                    "CAST(:provenance AS jsonb), '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, "
                    ":content_hash, now(), now())"
                ),
                {
                    "id": committed_artifact_id,
                    "workspace_id": fixture.workspace_id,
                    "session_id": fixture.session_id,
                    "logical_id": uuid4(),
                    "owner_id": fixture.user_id,
                    "payload": json.dumps(
                        {
                            "name": "Committed option",
                            "summary": "Written with its graph node",
                            "components": ["component"],
                            "origin": "HUMAN",
                            "feasibility_status": "UNKNOWN",
                        }
                    ),
                    "provenance": json.dumps(
                        {"origin": "HUMAN", "reference": "graph-integration-test"}
                    ),
                    "content_hash": f"sha256:{committed_artifact_id.hex * 2}",
                },
            )
            await SqlAlchemyReasoningGraphStore(session).add_node(
                GraphNode(
                    id=committed_node_id,
                    workspace_id=fixture.workspace_id,
                    session_id=fixture.session_id,
                    kind=ArtifactKind.ALTERNATIVE,
                    ref_id=committed_artifact_id,
                    label="Committed option",
                )
            )

        rolled_back_artifact_id, rolled_back_node_id = uuid4(), uuid4()
        async with sessions() as session:
            await session.begin()
            await session.execute(
                text(
                    "INSERT INTO reasoning_artifacts ("
                    "id, workspace_id, session_id, logical_id, kind, schema_version, version, "
                    "status, owner_actor_class, owner_actor_id, round, payload, provenance, "
                    "source_references, parent_relationships, metadata, content_hash, "
                    "created_at, updated_at"
                    ") SELECT :id, workspace_id, session_id, :logical_id, kind, schema_version, "
                    "version, status, owner_actor_class, owner_actor_id, round, payload, "
                    "provenance, "
                    "source_references, parent_relationships, metadata, :content_hash, "
                    "now(), now() "
                    "FROM reasoning_artifacts WHERE id = :source_id"
                ),
                {
                    "id": rolled_back_artifact_id,
                    "logical_id": uuid4(),
                    "content_hash": f"sha256:{rolled_back_artifact_id.hex * 2}",
                    "source_id": fixture.objective_id,
                },
            )
            await SqlAlchemyReasoningGraphStore(session).add_node(
                GraphNode(
                    id=rolled_back_node_id,
                    workspace_id=fixture.workspace_id,
                    session_id=fixture.session_id,
                    kind=ArtifactKind.OBJECTIVE,
                    ref_id=rolled_back_artifact_id,
                    label="Rolled back objective",
                )
            )
            await session.rollback()

        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM reasoning_artifacts "
                        "WHERE id IN (:committed, :rolled_back)"
                    ),
                    {"committed": committed_artifact_id, "rolled_back": rolled_back_artifact_id},
                )
                == 1
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM graph_nodes WHERE id IN (:committed, :rolled_back)"),
                    {"committed": committed_node_id, "rolled_back": rolled_back_node_id},
                )
                == 1
            )


@req("FR-503")
async def test_critique_response_revisions_requests_edges_and_events_share_one_transaction() -> (
    None
):
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "critique-response-atomic")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        target = _claim_artifact(
            fixture,
            uuid4(),
            uuid4(),
            statement="The option is affordable.",
            owner_actor_class=ActorClass.AGENT,
            owner_actor_id=fixture.agent_id,
        )
        critique_id = uuid4()
        critique_values: dict[str, object] = {
            "id": critique_id,
            "workspace_id": fixture.workspace_id,
            "session_id": fixture.session_id,
            "logical_id": uuid4(),
            "kind": ArtifactKind.CRITIQUE,
            "schema_version": 1,
            "version": 1,
            "status": LifecycleStatus.ACTIVE,
            "supersedes_id": None,
            "owner_actor_class": ActorClass.AGENT,
            "owner_actor_id": fixture.agent_id,
            "round": 1,
            "payload": CritiquePayload(
                target_id=target.id,
                critique_type=CritiqueType.EVIDENCE_GAP,
                severity=Severity.HIGH,
                argument="The affordability claim lacks evidence.",
                resolution=Resolution.OPEN,
            ),
            "provenance": Provenance(origin=ProvenanceOrigin.LLM, reference="fixture"),
            "source_references": (),
            "parent_relationships": (
                ParentRelationship(edge_type=GraphEdgeType.ATTACKS, target_artifact_id=target.id),
            ),
            "confidence": None,
            "metadata": {},
            "created_at": datetime(2026, 9, 7, 17, tzinfo=UTC),
            "updated_at": datetime(2026, 9, 7, 17, tzinfo=UTC),
        }
        critique_values["content_hash"] = artifact_content_hash(critique_values)
        critique = validate_artifact(critique_values)
        async with sessions.begin() as session:
            service = ArtifactCommitService(
                SqlAlchemyReasoningArtifactStore(session),
                SqlAlchemyReasoningGraphStore(session),
                SqlAlchemyReasoningLedger(session),
            )
            await service.commit(
                target,
                node_id=uuid4(),
                label="Target claim",
                context=ArtifactEventContext(
                    event_id=uuid4(),
                    correlation_id=uuid4(),
                    actor_class=ActorClass.AGENT,
                    actor_id=fixture.agent_id,
                    recorded_at=datetime(2026, 9, 7, 17, tzinfo=UTC),
                ),
            )
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
                    recorded_at=datetime(2026, 9, 7, 17, tzinfo=UTC),
                ),
            )

        definition = PinnedAgentDefinition(
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
        visible = (target, critique)
        response_id = uuid4()
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
            round=2,
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
        response = CritiqueResponseProposal(
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
            round=2,
            critique_id=critique.id,
            critique_version=1,
            target_artifact_id=target.id,
            target_artifact_version=1,
            disposition=CritiqueResponseDisposition.REVISE,
            rationale="Qualify the unsupported statement.",
            proposed_revision=ArtifactRevisionProposal(
                op="propose",
                kind=ArtifactKind.CLAIM,
                payload={
                    "statement": "The option may be affordable, subject to cost evidence.",
                    "claim_type": "FACTUAL",
                    "direction": "SUPPORTS",
                    "strength": "WEAK",
                    "supporting_evidence_ids": [],
                    "opposing_evidence_ids": [],
                    "review_status": "CONTESTED",
                },
            ),
        )
        operation = CritiqueResponseCommand(
            context=context,
            execution=TurnExecutionResult(
                proposal=response,
                provider="mock",
                model="integration-response-model",
                input_tokens=20,
                output_tokens=10,
                cost_usd=Decimal("0.003"),
                raw_artifact_ref="raw/response.json#sha256:" + "e" * 64,
            ),
            committed_at=datetime(2026, 9, 7, 18, tzinfo=UTC),
        )

        async def apply(session: AsyncSession) -> CritiqueResponseResult:
            artifacts = SqlAlchemyReasoningArtifactStore(session)
            graph = SqlAlchemyReasoningGraphStore(session)
            ledger = SqlAlchemyReasoningLedger(session)
            responses = SqlAlchemyCritiqueResponseStore(session)
            return await CritiqueResponseCommitter(artifacts, graph, ledger, responses).commit(
                operation
            )

        async with sessions() as session:
            await session.begin()
            rolled_back = await apply(session)
            await session.rollback()
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM reasoning_artifacts WHERE id IN (:critique, :target)"
                    ),
                    {
                        "critique": rolled_back.critique_revision_id,
                        "target": rolled_back.target_revision_id,
                    },
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM critique_response_requests WHERE response_id = :id"),
                    {"id": response_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM critique_response_results WHERE response_id = :id"),
                    {"id": response_id},
                )
                == 0
            )

        async with sessions.begin() as session:
            committed = await apply(session)
        async with sessions.begin() as session:
            retried = await apply(session)
        assert retried == committed
        async with engine.connect() as connection:
            counts = (
                await connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM critique_response_requests "
                        "WHERE response_id = :id), "
                        "(SELECT count(*) FROM critique_response_results "
                        "WHERE response_id = :id), "
                        "(SELECT count(*) FROM reasoning_artifacts "
                        "WHERE id IN (:critique, :target)), "
                        "(SELECT count(*) FROM graph_edges WHERE id IN "
                        "(:critique_supersedes, :target_supersedes, :responds_to)), "
                        "(SELECT count(*) FROM reasoning_events WHERE id = :event_id)"
                    ),
                    {
                        "id": response_id,
                        "critique": committed.critique_revision_id,
                        "target": committed.target_revision_id,
                        "critique_supersedes": response_commit_id(
                            response_id, "critique-supersedes-edge"
                        ),
                        "target_supersedes": response_commit_id(
                            response_id, "target-supersedes-edge"
                        ),
                        "responds_to": response_commit_id(
                            response_id, "target-relationship-edge", 0
                        ),
                        "event_id": committed.response_event_id,
                    },
                )
            ).one()
            assert tuple(counts) == (1, 1, 2, 3, 1)
            rls = (
                await connection.execute(
                    text(
                        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                        "WHERE relname IN "
                        "('critique_response_requests', 'critique_response_results') "
                        "ORDER BY relname"
                    )
                )
            ).all()
            assert [tuple(row) for row in rls] == [
                ("critique_response_requests", True, True),
                ("critique_response_results", True, True),
            ]
        for table in ("critique_response_requests", "critique_response_results"):
            with pytest.raises(DBAPIError, match="append-only") as mutation:
                async with engine.begin() as connection:
                    await connection.execute(
                        text(f"UPDATE {table} SET schema_version = 1 WHERE response_id = :id"),
                        {"id": response_id},
                    )
            assert getattr(mutation.value.orig, "sqlstate", None) == "27000"


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_graph_uniqueness_and_self_loop_constraints() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "graph-unique")
            objective_node = await _insert_graph_node(
                connection, fixture, ref_id=fixture.objective_id, kind="OBJECTIVE"
            )
            constraint_node = await _insert_graph_node(
                connection, fixture, ref_id=fixture.constraint_id, kind="CONSTRAINT"
            )

        with pytest.raises(DBAPIError) as duplicate_node:
            async with engine.begin() as connection:
                await _insert_graph_node(
                    connection, fixture, ref_id=fixture.objective_id, kind="OBJECTIVE"
                )
        assert getattr(duplicate_node.value.orig, "sqlstate", None) == "23505"

        with pytest.raises(DBAPIError) as duplicate_edge:
            await _insert_duplicate_graph_edges(
                engine, fixture, from_node=constraint_node, to_node=objective_node
            )
        assert getattr(duplicate_edge.value.orig, "sqlstate", None) == "23505"

        with pytest.raises(DBAPIError, match="ck_graph_edges_no_self_loop") as self_loop:
            async with engine.begin() as connection:
                await _insert_graph_edge(
                    connection,
                    fixture,
                    from_node=objective_node,
                    to_node=objective_node,
                    edge_type="SUPERSEDES",
                )
        assert getattr(self_loop.value.orig, "sqlstate", None) == "23514"


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_graph_endpoint_function_matches_the_closed_phase_3_matrix() -> None:
    kinds = tuple(kind.value for kind in ArtifactKind)
    edge_types = tuple(edge_type.value for edge_type in GraphEdgeType)
    expected: set[tuple[str, str, str]] = set()

    def allow(edge_type: str, sources: tuple[str, ...], targets: tuple[str, ...]) -> None:
        expected.update(
            (edge_type, source_kind, target_kind)
            for source_kind in sources
            for target_kind in targets
        )

    allow("SUPPORTS", ("EVIDENCE", "CLAIM"), ("CLAIM",))
    allow("OPPOSES", ("EVIDENCE", "CLAIM"), ("CLAIM",))
    allow("CONTRADICTS", ("CLAIM",), ("CLAIM",))
    allow("DERIVED_FROM", ("CLAIM",), ("CLAIM", "ASSUMPTION", "FACT"))
    allow("BASED_ON_ASSUMPTION", ("CLAIM", "ALTERNATIVE"), ("ASSUMPTION",))
    allow("FORMALIZES", ("PROPOSITION",), ("CLAIM",))
    allow("QUANTIFIES", ("UNCERTAINTY",), kinds)
    allow("IMPACTS", ("ALTERNATIVE",), ("OBJECTIVE",))
    allow("CONSTRAINS", ("CONSTRAINT",), ("ALTERNATIVE", "OBJECTIVE"))
    allow("VIOLATES", ("ALTERNATIVE",), ("CONSTRAINT",))
    allow("SATISFIES", ("ALTERNATIVE",), ("CONSTRAINT",))
    allow("INFEASIBLE_UNKNOWN", ("ALTERNATIVE",), ("CONSTRAINT",))
    allow("ATTACKS", ("CRITIQUE",), kinds)
    allow("RESPONDS_TO", kinds, ("CRITIQUE",))
    expected.update(("SUPERSEDES", kind, kind) for kind in kinds)
    allow("ADVOCATES", ("POSITION",), ("ALTERNATIVE",))

    async with _migrated_database() as engine, engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT edge_type, from_kind, to_kind "
                "FROM unnest(CAST(:edge_types AS text[])) AS edge_type "
                "CROSS JOIN unnest(CAST(:from_kinds AS text[])) AS from_kind "
                "CROSS JOIN unnest(CAST(:to_kinds AS text[])) AS to_kind "
                "WHERE graph_edge_endpoint_pair_allowed(edge_type, from_kind, to_kind)"
            ),
            {"edge_types": edge_types, "from_kinds": kinds, "to_kinds": kinds},
        )
        assert {tuple(row) for row in rows} == expected


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_graph_deferred_tenant_kind_and_endpoint_validation() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            first = await _insert_session_graph(connection, "graph-integrity-a")
            second = await _insert_session_graph(connection, "graph-integrity-b")
            alternative_id, _ = await _insert_artifact(
                connection,
                workspace_id=first.workspace_id,
                session_id=first.session_id,
                owner_id=first.user_id,
                kind="ALTERNATIVE",
                payload={
                    "name": "Unprojected option",
                    "summary": "Used to test cached-kind validation",
                    "components": ["component"],
                    "origin": "HUMAN",
                    "feasibility_status": "UNKNOWN",
                },
            )
            first_objective = await _insert_graph_node(
                connection, first, ref_id=first.objective_id, kind="OBJECTIVE"
            )
            first_constraint = await _insert_graph_node(
                connection, first, ref_id=first.constraint_id, kind="CONSTRAINT"
            )
            second_objective = await _insert_graph_node(
                connection, second, ref_id=second.objective_id, kind="OBJECTIVE"
            )

        with pytest.raises(DBAPIError, match="kind must match") as mismatched_kind:
            await _insert_graph_node_and_validate(engine, first, ref_id=alternative_id, kind="FACT")
        assert getattr(mismatched_kind.value.orig, "sqlstate", None) == "23514"

        with pytest.raises(DBAPIError) as cross_tenant_node:
            await _insert_graph_node_and_validate(
                engine, first, ref_id=second.objective_id, kind="OBJECTIVE"
            )
        assert getattr(cross_tenant_node.value.orig, "sqlstate", None) == "23503"

        with pytest.raises(DBAPIError, match="not allowed for endpoint kinds") as invalid_pair:
            await _insert_graph_edge_and_validate(
                engine,
                first,
                from_node=first_objective,
                to_node=first_constraint,
                edge_type="SATISFIES",
            )
        assert getattr(invalid_pair.value.orig, "sqlstate", None) == "23514"

        with pytest.raises(DBAPIError) as cross_tenant_edge:
            await _insert_graph_edge_and_validate(
                engine,
                first,
                from_node=first_constraint,
                to_node=second_objective,
                edge_type="CONSTRAINS",
            )
        assert getattr(cross_tenant_edge.value.orig, "sqlstate", None) == "23503"

        async with engine.begin() as connection:
            await _insert_graph_edge(
                connection,
                first,
                from_node=first_constraint,
                to_node=first_objective,
                edge_type="CONSTRAINS",
            )

        with pytest.raises(DBAPIError, match="invalidates an incident edge") as invalid_update:
            await _update_graph_node_kind_and_validate(
                engine, node_id=first_constraint, ref_id=alternative_id, kind="ALTERNATIVE"
            )
        assert getattr(invalid_update.value.orig, "sqlstate", None) == "23514"


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_forced_rls_isolates_graph_tables() -> None:
    role = "agora_t304_app"
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            first = await _insert_session_graph(connection, "graph-rls-a")
            second = await _insert_session_graph(connection, "graph-rls-b")
            await _insert_graph_node(connection, first, ref_id=first.objective_id, kind="OBJECTIVE")
            await _insert_graph_node(
                connection, second, ref_id=second.objective_id, kind="OBJECTIVE"
            )
            await connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
            await connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await connection.execute(
                text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON graph_nodes, graph_edges TO {role}")
            )
            rows = await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = ANY(:tables) ORDER BY relname"
                ),
                {"tables": list(_GRAPH_TABLES)},
            )
            assert [tuple(row) for row in rows] == [
                (name, True, True) for name in sorted(_GRAPH_TABLES)
            ]

        async with engine.begin() as connection:
            await connection.execute(text(f"SET ROLE {role}"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(first.workspace_id)},
            )
            assert await connection.scalar(text("SELECT count(*) FROM graph_nodes")) == 1
            result = await connection.execute(
                text("UPDATE graph_nodes SET label = 'hidden' WHERE workspace_id = :workspace_id"),
                {"workspace_id": second.workspace_id},
            )
            assert result.rowcount == 0

        with pytest.raises(DBAPIError, match="row-level security policy") as cross_tenant_insert:
            await _insert_graph_node_as_role(
                engine,
                role=role,
                current_workspace_id=first.workspace_id,
                fixture=second,
            )
        assert getattr(cross_tenant_insert.value.orig, "sqlstate", None) == "42501"


@dataclass(frozen=True)
class TraversalFixture:
    """A four-node ``SUPERSEDES`` cycle plus one ``CONSTRAINS`` edge into its head.

    ``chain[0] -> chain[1] -> chain[2] -> chain[3] -> chain[0]`` are SUPERSEDES
    edges between ALTERNATIVE nodes, so every traversal direction eventually
    revisits its own root and must terminate on path-based cycle safety rather
    than on the depth bound alone.
    """

    tenant: TenantFixture
    chain: tuple[UUID, ...]
    constraint_node: UUID


async def _insert_traversal_graph(connection: AsyncConnection, label: str) -> TraversalFixture:
    fixture = await _insert_session_graph(connection, label)
    chain: list[UUID] = []
    for index in range(4):
        artifact_id, _ = await _insert_artifact(
            connection,
            workspace_id=fixture.workspace_id,
            session_id=fixture.session_id,
            owner_id=fixture.user_id,
            kind="ALTERNATIVE",
            payload={
                "name": f"Option {index}",
                "summary": f"Traversal fixture option {index}",
                "components": ["component"],
                "origin": "HUMAN",
                "feasibility_status": "UNKNOWN",
            },
        )
        chain.append(
            await _insert_graph_node(connection, fixture, ref_id=artifact_id, kind="ALTERNATIVE")
        )
    for position in range(len(chain)):
        await _insert_graph_edge(
            connection,
            fixture,
            from_node=chain[position],
            to_node=chain[(position + 1) % len(chain)],
            edge_type="SUPERSEDES",
        )
    constraint_node = await _insert_graph_node(
        connection, fixture, ref_id=fixture.constraint_id, kind="CONSTRAINT"
    )
    await _insert_graph_edge(
        connection,
        fixture,
        from_node=constraint_node,
        to_node=chain[0],
        edge_type="CONSTRAINS",
    )
    return TraversalFixture(tenant=fixture, chain=tuple(chain), constraint_node=constraint_node)


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_trace_backward_and_forward_survive_a_supersedes_cycle_without_duplicates() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            graph = await _insert_traversal_graph(connection, "traverse-cycle")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            store = SqlAlchemyReasoningGraphStore(session)
            backward = await store.trace_backward(
                graph.tenant.workspace_id, graph.tenant.session_id, graph.chain[0]
            )
            forward = await store.trace_forward(
                graph.tenant.workspace_id, graph.tenant.session_id, graph.chain[0]
            )

        backward_ids = [node.id for node in backward.nodes]
        forward_ids = [node.id for node in forward.nodes]
        assert len(backward_ids) == len(set(backward_ids))
        assert len(forward_ids) == len(set(forward_ids))
        assert not backward.truncated
        assert not forward.truncated
        assert set(backward_ids) == {graph.constraint_node, *graph.chain}
        assert set(forward_ids) == set(graph.chain)


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_trace_backward_depth_zero_returns_only_the_root_with_no_edges() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            graph = await _insert_traversal_graph(connection, "traverse-depth-zero")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            result = await SqlAlchemyReasoningGraphStore(session).trace_backward(
                graph.tenant.workspace_id,
                graph.tenant.session_id,
                graph.chain[0],
                max_depth=0,
            )

        assert [node.id for node in result.nodes] == [graph.chain[0]]
        assert result.edges == ()
        assert result.truncated


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_trace_backward_truncates_before_reaching_the_full_cycle() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            graph = await _insert_traversal_graph(connection, "traverse-truncate")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            result = await SqlAlchemyReasoningGraphStore(session).trace_backward(
                graph.tenant.workspace_id,
                graph.tenant.session_id,
                graph.chain[0],
                max_depth=1,
            )

        assert result.truncated
        assert {node.id for node in result.nodes} == {
            graph.chain[0],
            graph.chain[3],
            graph.constraint_node,
        }


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_trace_forward_filters_by_edge_type() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            graph = await _insert_traversal_graph(connection, "traverse-edge-filter")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            result = await SqlAlchemyReasoningGraphStore(session).trace_forward(
                graph.tenant.workspace_id,
                graph.tenant.session_id,
                graph.constraint_node,
                edge_types=frozenset({GraphEdgeType.SUPERSEDES}),
            )

        assert [node.id for node in result.nodes] == [graph.constraint_node]
        assert result.edges == ()
        assert not result.truncated


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_subgraph_radius_two_reaches_neighbors_of_neighbors_only() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            graph = await _insert_traversal_graph(connection, "traverse-subgraph")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            result = await SqlAlchemyReasoningGraphStore(session).subgraph(
                graph.tenant.workspace_id,
                graph.tenant.session_id,
                (graph.constraint_node,),
                max_depth=2,
            )

        assert {node.id for node in result.nodes} == {
            graph.constraint_node,
            graph.chain[0],
            graph.chain[1],
            graph.chain[3],
        }
        assert result.truncated


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_trace_forward_paginates_deterministically_and_binds_cursor_to_query() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            graph = await _insert_traversal_graph(connection, "traverse-pagination")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            store = SqlAlchemyReasoningGraphStore(session)
            expected = await store.trace_forward(
                graph.tenant.workspace_id,
                graph.tenant.session_id,
                graph.chain[0],
            )
            pages = []
            cursor = None
            while True:
                page = await store.trace_forward(
                    graph.tenant.workspace_id,
                    graph.tenant.session_id,
                    graph.chain[0],
                    page_size=3,
                    cursor=cursor,
                )
                pages.append(page)
                cursor = page.next_cursor
                if cursor is None:
                    break

            first_cursor = pages[0].next_cursor
            assert first_cursor is not None
            with pytest.raises(ValueError, match="invalid traversal cursor"):
                await store.trace_backward(
                    graph.tenant.workspace_id,
                    graph.tenant.session_id,
                    graph.chain[0],
                    page_size=3,
                    cursor=first_cursor,
                )

        actual_nodes = tuple(node for page in pages for node in page.nodes)
        actual_edges = tuple(edge for page in pages for edge in page.edges)
        assert actual_nodes == expected.nodes
        assert actual_edges == expected.edges
        assert all(page.truncated == expected.truncated for page in pages)
        assert len(pages) == 3
        assert all(len(page.nodes) + len(page.edges) <= 3 for page in pages)


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_traversal_stays_within_workspace_and_session_boundaries() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            first = await _insert_traversal_graph(connection, "traverse-isolation-a")
            second = await _insert_traversal_graph(connection, "traverse-isolation-b")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            store = SqlAlchemyReasoningGraphStore(session)
            first_backward = await store.trace_backward(
                first.tenant.workspace_id, first.tenant.session_id, first.chain[0]
            )
            cross_tenant = await store.trace_backward(
                second.tenant.workspace_id, second.tenant.session_id, first.chain[0]
            )

        first_ids = {node.id for node in first_backward.nodes}
        assert first_ids.isdisjoint({node.id for node in cross_tenant.nodes} - first_ids)
        assert cross_tenant.nodes == ()
        assert cross_tenant.edges == ()
        assert not cross_tenant.truncated


async def _insert_incomplete_session(
    engine: AsyncEngine, workspace_id: UUID, user_id: UUID
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO sessions ("
                "id, workspace_id, problem_statement, max_rounds, budget_tokens, "
                "budget_usd, created_by"
                ") VALUES ("
                ":id, :workspace_id, 'Incomplete session', 2, 100, 1.00, :user_id"
                ")"
            ),
            {"id": uuid4(), "workspace_id": workspace_id, "user_id": user_id},
        )


async def _insert_session_as_role(
    engine: AsyncEngine,
    *,
    role: str,
    current_workspace_id: UUID,
    row_workspace_id: UUID,
    created_by: UUID,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"SET ROLE {role}"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(current_workspace_id)},
        )
        await connection.execute(
            text(
                "INSERT INTO sessions ("
                "id, workspace_id, problem_statement, max_rounds, budget_tokens, "
                "budget_usd, created_by"
                ") VALUES ("
                ":id, :workspace_id, 'Cross tenant', 2, 100, 1.00, :created_by"
                ")"
            ),
            {"id": uuid4(), "workspace_id": row_workspace_id, "created_by": created_by},
        )


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_jsonb_payload_decimal_and_envelope_validation() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "validators")
            decimal_results = await connection.execute(
                text(
                    "SELECT jsonb_decimal_string(CAST(:valid AS jsonb)), "
                    "jsonb_decimal_string(CAST(:wrong_separator AS jsonb)), "
                    "jsonb_decimal_string(CAST(:trailing_zero AS jsonb)), "
                    "jsonb_decimal_string(CAST(:json_number AS jsonb))"
                ),
                {
                    "valid": json.dumps("0.5"),
                    "wrong_separator": json.dumps("0x5"),
                    "trailing_zero": json.dumps("0.50"),
                    "json_number": json.dumps(0.5),
                },
            )
            assert decimal_results.one() == (True, False, False, False)
            await _insert_artifact(
                connection,
                workspace_id=fixture.workspace_id,
                session_id=fixture.session_id,
                owner_id=fixture.user_id,
                kind="FACT",
                payload={"statement": "Verified fact", "verification": "SOURCE_VERIFIED"},
                source_references=[
                    {
                        "reference": "source-valid",
                        "locator": {"page": 1},
                        "content_hash": f"sha256:{'b' * 64}",
                        "retrieved_at": "2026-09-05T12:00:00Z",
                    }
                ],
            )

        with pytest.raises(DBAPIError, match="ck_reasoning_artifacts_payload") as malformed_payload:
            async with engine.begin() as connection:
                await _insert_artifact(
                    connection,
                    workspace_id=fixture.workspace_id,
                    session_id=fixture.session_id,
                    owner_id=fixture.user_id,
                    kind="OBJECTIVE",
                    payload={**_objective_payload(), "unexpected": True},
                )
        assert getattr(malformed_payload.value.orig, "sqlstate", None) == "23514"

        with pytest.raises(
            DBAPIError, match="ck_reasoning_artifacts_envelope"
        ) as malformed_envelope:
            async with engine.begin() as connection:
                await _insert_artifact(
                    connection,
                    workspace_id=fixture.workspace_id,
                    session_id=fixture.session_id,
                    owner_id=fixture.user_id,
                    kind="FACT",
                    payload={"statement": "Verified fact", "verification": "SOURCE_VERIFIED"},
                    source_references=[
                        {
                            "reference": "source-1",
                            "locator": {"page": 1},
                            "content_hash": f"sha256:{'a' * 64}",
                            "retrieved_at": "2026-09-05 12:00:00",
                        }
                    ],
                )
        assert getattr(malformed_envelope.value.orig, "sqlstate", None) == "23514"


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_tenant_session_foreign_keys_revision_chain_and_references() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            first = await _insert_session_graph(connection, "integrity-a")
            second = await _insert_session_graph(connection, "integrity-b")

        with pytest.raises(DBAPIError) as cross_tenant_binding:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO session_objectives (workspace_id, session_id, artifact_id) "
                        "VALUES (:workspace_id, :session_id, :artifact_id)"
                    ),
                    {
                        "workspace_id": first.workspace_id,
                        "session_id": first.session_id,
                        "artifact_id": second.objective_id,
                    },
                )
        assert getattr(cross_tenant_binding.value.orig, "sqlstate", None) == "23503"

        with pytest.raises(DBAPIError, match="target must exist") as cross_session_reference:
            async with engine.begin() as connection:
                await _insert_artifact(
                    connection,
                    workspace_id=first.workspace_id,
                    session_id=first.session_id,
                    owner_id=first.user_id,
                    kind="OBJECTIVE",
                    payload=_objective_payload("Referenced objective"),
                    parent_relationships=[
                        {
                            "edge_type": "DERIVED_FROM",
                            "target_artifact_id": str(second.objective_id),
                        }
                    ],
                )
        assert getattr(cross_session_reference.value.orig, "sqlstate", None) == "23503"

        with pytest.raises(DBAPIError, match="artifact revision must supersede") as bad_revision:
            async with engine.begin() as connection:
                await _insert_artifact(
                    connection,
                    workspace_id=first.workspace_id,
                    session_id=first.session_id,
                    owner_id=first.user_id,
                    kind="OBJECTIVE",
                    payload=_objective_payload("Invalid revision"),
                    logical_id=uuid4(),
                    version=2,
                    supersedes_id=first.objective_id,
                )
        assert getattr(bad_revision.value.orig, "sqlstate", None) == "23514"

        async with engine.begin() as connection:
            revision_id, _ = await _insert_artifact(
                connection,
                workspace_id=first.workspace_id,
                session_id=first.session_id,
                owner_id=first.user_id,
                kind="OBJECTIVE",
                payload=_objective_payload("Valid revision"),
                logical_id=first.objective_logical_id,
                version=2,
                supersedes_id=first.objective_id,
            )
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT version FROM reasoning_artifacts WHERE id = :id"),
                    {"id": revision_id},
                )
                == 2
            )


@req("FR-102", "FR-312")
async def test_deferred_session_binding_completeness_and_artifact_kind() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            workspace_id, user_id, _ = await _insert_tenant(connection, "incomplete")
        with pytest.raises(
            DBAPIError, match="requires at least one agent and objective"
        ) as incomplete:
            await _insert_incomplete_session(engine, workspace_id, user_id)
        assert getattr(incomplete.value.orig, "sqlstate", None) == "23514"

        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "bindings")

        with pytest.raises(
            DBAPIError, match="session_objectives requires artifact kind OBJECTIVE"
        ) as kind:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO session_objectives (workspace_id, session_id, artifact_id) "
                        "VALUES (:workspace_id, :session_id, :artifact_id)"
                    ),
                    {
                        "workspace_id": fixture.workspace_id,
                        "session_id": fixture.session_id,
                        "artifact_id": fixture.constraint_id,
                    },
                )
        assert getattr(kind.value.orig, "sqlstate", None) == "23514"

        with pytest.raises(
            DBAPIError, match="requires at least one agent and objective"
        ) as deletion:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM session_objectives WHERE session_id = :session_id"),
                    {"session_id": fixture.session_id},
                )
        assert getattr(deletion.value.orig, "sqlstate", None) == "23514"


@req("FR-303")
async def test_reasoning_artifacts_are_immutable_and_cannot_be_deleted() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "immutable")

        with pytest.raises(DBAPIError, match="reasoning artifact content is immutable") as mutation:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE reasoning_artifacts "
                        "SET payload = jsonb_set(payload, '{name}', CAST(:name AS jsonb)) "
                        "WHERE id = :id"
                    ),
                    {"id": fixture.objective_id, "name": json.dumps("Tampered")},
                )
        assert getattr(mutation.value.orig, "sqlstate", None) == "27000"

        with pytest.raises(DBAPIError, match="reasoning artifacts cannot be deleted") as deletion:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM reasoning_artifacts WHERE id = :id"),
                    {"id": fixture.objective_id},
                )
        assert getattr(deletion.value.orig, "sqlstate", None) == "27000"

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE reasoning_artifacts "
                    "SET status = 'SUPERSEDED', updated_at = now() WHERE id = :id"
                ),
                {"id": fixture.objective_id},
            )


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_membership_history_and_durable_usage_are_tenant_safe_and_append_only() -> None:
    async with _migrated_database() as engine:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "coordinator-policy")
            injected_id, injected_logical_id = uuid4(), uuid4()
            second_injected_id, second_injected_logical_id = uuid4(), uuid4()
            malformed_budget_id, malformed_budget_logical_id = uuid4(), uuid4()
            await connection.execute(
                text(
                    "INSERT INTO agent_definitions ("
                    "id, workspace_id, logical_id, version, name, domain, role_kind, strategy_ref, "
                    "strategy_ver, prompt_ref, prompt_hash, budget, status) VALUES ("
                    ":id, :workspace_id, :logical_id, 1, 'injected', 'risk', 'domain_expert', "
                    "'fixture', '1', 'prompts/injected.txt', :prompt_hash, "
                    "CAST(:budget AS jsonb), 'ACTIVE'), ("
                    ":second_id, :workspace_id, :second_logical_id, 1, 'second-injected', "
                    "'social', "
                    "'domain_expert', 'fixture', '1', 'prompts/second-injected.txt', :prompt_hash, "
                    "CAST(:budget AS jsonb), 'ACTIVE'), ("
                    ":malformed_id, :workspace_id, :malformed_logical_id, 1, 'malformed-budget', "
                    "'fixture', 'domain_expert', 'fixture', '1', 'prompts/malformed.txt', "
                    ":prompt_hash, CAST(:malformed_budget AS jsonb), 'ACTIVE')"
                ),
                {
                    "id": injected_id,
                    "second_id": second_injected_id,
                    "malformed_id": malformed_budget_id,
                    "workspace_id": fixture.workspace_id,
                    "logical_id": injected_logical_id,
                    "second_logical_id": second_injected_logical_id,
                    "malformed_logical_id": malformed_budget_logical_id,
                    "prompt_hash": f"sha256:{'a' * 64}",
                    "budget": json.dumps({"max_tokens": 40, "max_cost_usd": "0.5"}),
                    "malformed_budget": json.dumps({"max_tokens": 1.5, "max_cost_usd": "1"}),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO llm_call_records ("
                    "id, workspace_id, session_id, agent_def_id, provider, model, input_tokens, "
                    "output_tokens, cost_usd, latency_ms, finish_reason, retry_attempts, "
                    "raw_artifact_ref, correlation_id) VALUES "
                    "(:first, :workspace_id, :session_id, :agent_id, 'mock', 'fixture', 20, 5, "
                    "0.10, 1, 'stop', 0, 'raw/one.json#sha256:aaa', 'corr'), "
                    "(:second, :workspace_id, :session_id, :agent_id, 'mock', 'fixture', 10, 7, "
                    "0.20, 1, 'stop', 0, 'raw/two.json#sha256:bbb', 'corr')"
                ),
                {
                    "first": uuid4(),
                    "second": uuid4(),
                    "workspace_id": fixture.workspace_id,
                    "session_id": fixture.session_id,
                    "agent_id": injected_id,
                },
            )

        event_id = uuid4()
        recorded_at = datetime(2026, 9, 7, 12, tzinfo=UTC)
        async with sessions.begin() as session:
            ledger = SqlAlchemyReasoningLedger(session)
            correlation_id = uuid4()
            await ledger.append(
                LedgerAppend(
                    id=event_id,
                    workspace_id=fixture.workspace_id,
                    session_id=fixture.session_id,
                    event_type="SESSION_AGENT_INJECTED",
                    payload_schema_version=1,
                    correlation_id=correlation_id,
                    actor_class=ActorClass.HUMAN,
                    actor_id=fixture.user_id,
                    round=1,
                    payload={
                        "agent_definition_id": str(injected_id),
                        "effective_round": 2,
                    },
                    recorded_at=recorded_at,
                )
            )
            store = SqlAlchemyCoordinatorPolicyStore(session)
            await store.add_intervention(
                MembershipIntervention(
                    event_id=event_id,
                    workspace_id=fixture.workspace_id,
                    session_id=fixture.session_id,
                    kind=MembershipInterventionKind.INJECT,
                    agent_definition_id=injected_id,
                    effective_round=2,
                    actor_id=fixture.user_id,
                    correlation_id=correlation_id,
                    reason="Add risk coverage",
                    recorded_at=recorded_at,
                )
            )
            second_event_id = uuid4()
            second_correlation_id = uuid4()
            earlier_recorded_at = recorded_at - timedelta(minutes=1)
            await ledger.append(
                LedgerAppend(
                    id=second_event_id,
                    workspace_id=fixture.workspace_id,
                    session_id=fixture.session_id,
                    event_type="SESSION_AGENT_INJECTED",
                    payload_schema_version=1,
                    correlation_id=second_correlation_id,
                    actor_class=ActorClass.HUMAN,
                    actor_id=fixture.user_id,
                    round=1,
                    payload={
                        "agent_definition_id": str(second_injected_id),
                        "effective_round": 2,
                    },
                    recorded_at=earlier_recorded_at,
                )
            )
            await store.add_intervention(
                MembershipIntervention(
                    event_id=second_event_id,
                    workspace_id=fixture.workspace_id,
                    session_id=fixture.session_id,
                    kind=MembershipInterventionKind.INJECT,
                    agent_definition_id=second_injected_id,
                    effective_round=2,
                    actor_id=fixture.user_id,
                    correlation_id=second_correlation_id,
                    reason="Add social coverage",
                    recorded_at=earlier_recorded_at,
                )
            )
            before = await store.membership(fixture.workspace_id, fixture.session_id, round=1)
            after = await store.membership(fixture.workspace_id, fixture.session_id, round=2)
            usage = await store.session_usage(fixture.workspace_id, fixture.session_id)
            agent_usage = await store.agent_usage(
                fixture.workspace_id, fixture.session_id, injected_id
            )
            ceiling = await store.agent_ceiling(fixture.workspace_id, injected_id)

        assert tuple(item.id for item in before.definitions) == (fixture.agent_id,)
        assert tuple(item.id for item in after.definitions) == (
            fixture.agent_id,
            injected_id,
            second_injected_id,
        )
        assert usage.tokens == agent_usage.tokens == 42
        assert usage.cost_usd == agent_usage.cost_usd == Decimal("0.30000000")
        assert ceiling is not None
        assert (ceiling.max_tokens, ceiling.max_usd) == (40, Decimal("0.5"))

        async with sessions.begin() as session:
            with pytest.raises(ValueError, match="agent budget ceiling is invalid"):
                await SqlAlchemyCoordinatorPolicyStore(session).agent_ceiling(
                    fixture.workspace_id, malformed_budget_id
                )

        async with engine.connect() as connection:
            forced = await connection.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'session_agent_interventions'"
                )
            )
            assert forced.one() == (True, True)
            assert await connection.scalar(
                text("SELECT referenced_at IS NOT NULL FROM agent_definitions WHERE id = :id"),
                {"id": injected_id},
            )

        with pytest.raises(DBAPIError, match="append-only") as mutation:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE session_agent_interventions SET reason = 'tampered' "
                        "WHERE event_id = :event_id"
                    ),
                    {"event_id": event_id},
                )
        assert getattr(mutation.value.orig, "sqlstate", None) == "27000"

        await asyncio.to_thread(command.check, _alembic_config())


async def _commit_invalid_reference(
    sessions: async_sessionmaker[AsyncSession],
    fixture: TenantFixture,
    artifact: ReasoningArtifact,
    *,
    node_id: UUID,
    relationship_edge_id: UUID,
    event_id: UUID,
) -> None:
    async with sessions.begin() as session:
        service = ArtifactCommitService(
            SqlAlchemyReasoningArtifactStore(session),
            SqlAlchemyReasoningGraphStore(session),
            SqlAlchemyReasoningLedger(session),
        )
        await service.commit(
            artifact,
            node_id=node_id,
            relationship_edge_ids=(relationship_edge_id,),
            label="Deferred reference failure",
            context=_artifact_context(fixture, event_id),
        )


@req("FR-302")
async def test_artifact_commit_service_is_atomic_and_preserves_additive_lifecycle() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "artifact-service")
            await _insert_graph_node(
                connection, fixture, ref_id=fixture.objective_id, kind="OBJECTIVE"
            )

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        rolled_back_artifact_id = uuid4()
        rolled_back_node_id, rolled_back_edge_id, rolled_back_event_id = uuid4(), uuid4(), uuid4()
        rolled_back = _claim_artifact(
            fixture,
            rolled_back_artifact_id,
            uuid4(),
            statement="Must roll back",
            parent_relationships=(
                ParentRelationship(
                    edge_type=GraphEdgeType.DERIVED_FROM,
                    target_artifact_id=fixture.objective_id,
                ),
            ),
        )
        with pytest.raises(DBAPIError, match="graph edge type is not allowed"):
            await _commit_invalid_reference(
                sessions,
                fixture,
                rolled_back,
                node_id=rolled_back_node_id,
                relationship_edge_id=rolled_back_edge_id,
                event_id=rolled_back_event_id,
            )

        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM graph_edges WHERE id = :id"),
                    {"id": rolled_back_edge_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM reasoning_artifacts WHERE id = :id"),
                    {"id": rolled_back_artifact_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM graph_nodes WHERE id = :id"),
                    {"id": rolled_back_node_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM reasoning_events WHERE id = :id"),
                    {"id": rolled_back_event_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text("SELECT next_seq FROM session_ledger_heads WHERE session_id = :id"),
                    {"id": fixture.session_id},
                )
                == 1
            )

        artifact_id, logical_id, node_id = uuid4(), uuid4(), uuid4()
        artifact = _claim_artifact(fixture, artifact_id, logical_id)
        async with sessions.begin() as session:
            service = ArtifactCommitService(
                SqlAlchemyReasoningArtifactStore(session),
                SqlAlchemyReasoningGraphStore(session),
                SqlAlchemyReasoningLedger(session),
            )
            committed = await service.commit(
                artifact,
                node_id=node_id,
                label="Atomic claim",
                context=_artifact_context(fixture, uuid4()),
            )
            assert committed.event.ledger_seq == 1

        revision_id, revision_node_id = uuid4(), uuid4()
        revision = _claim_artifact(
            fixture,
            revision_id,
            logical_id,
            version=2,
            supersedes_id=artifact_id,
            statement="Atomic claim corrected",
        )
        async with sessions.begin() as session:
            service = ArtifactCommitService(
                SqlAlchemyReasoningArtifactStore(session),
                SqlAlchemyReasoningGraphStore(session),
                SqlAlchemyReasoningLedger(session),
            )
            revised = await service.revise(
                revision,
                node_id=revision_node_id,
                edge_id=uuid4(),
                label="Atomic claim corrected",
                reason="New primary evidence",
                context=_artifact_context(fixture, uuid4()),
            )
            assert revised.event.ledger_seq == 2

        async with sessions.begin() as session:
            service = ArtifactCommitService(
                SqlAlchemyReasoningArtifactStore(session),
                SqlAlchemyReasoningGraphStore(session),
                SqlAlchemyReasoningLedger(session),
            )
            withdrawn = await service.withdraw(
                fixture.workspace_id,
                fixture.session_id,
                revision_id,
                reason="Author withdrew the corrected claim",
                warrant_artifact_ids=(fixture.objective_id,),
                context=_artifact_context(fixture, uuid4()),
            )
            assert withdrawn.event.ledger_seq == 3
            assert withdrawn.artifact.status is LifecycleStatus.WITHDRAWN

        async with engine.connect() as connection:
            lifecycle = [
                tuple(row)
                for row in (
                    await connection.execute(
                        text(
                            "SELECT id, status, version, supersedes_id FROM reasoning_artifacts "
                            "WHERE logical_id = :logical_id ORDER BY version"
                        ),
                        {"logical_id": logical_id},
                    )
                ).all()
            ]
            assert lifecycle == [
                (artifact_id, "SUPERSEDED", 1, None),
                (revision_id, "WITHDRAWN", 2, artifact_id),
            ]
            edge = (
                await connection.execute(
                    text(
                        "SELECT from_node, to_node, edge_type, qualifier FROM graph_edges "
                        "WHERE from_node = :from_node"
                    ),
                    {"from_node": revision_node_id},
                )
            ).one()
            assert tuple(edge[:3]) == (revision_node_id, node_id, "SUPERSEDES")
            assert edge.qualifier == {"reason": "New primary evidence"}
            events = [
                tuple(row)
                for row in (
                    await connection.execute(
                        text(
                            "SELECT ledger_seq, event_type, payload ->> 'artifact_id' "
                            "FROM reasoning_events WHERE session_id = :session_id "
                            "ORDER BY ledger_seq"
                        ),
                        {"session_id": fixture.session_id},
                    )
                ).all()
            ]
            assert events == [
                (1, "ARTIFACT_COMMITTED", str(artifact_id)),
                (2, "ARTIFACT_REVISED", str(revision_id)),
                (3, "ARTIFACT_WITHDRAWN", str(revision_id)),
            ]


@req("FR-210")
async def test_agent_proposal_commit_is_atomic_and_fabricated_reference_writes_nothing() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "agent-proposal-commit")

        database = Database(engine)
        proposition_id, proposition_logical_id, proposition_node_id = uuid4(), uuid4(), uuid4()
        async with database.session(fixture.workspace_id) as session:
            proposition = _proposition_artifact(fixture, proposition_id, proposition_logical_id)
            await SqlAlchemyReasoningArtifactStore(session).add(proposition)
            await SqlAlchemyReasoningGraphStore(session).add_node(
                GraphNode(
                    id=proposition_node_id,
                    workspace_id=fixture.workspace_id,
                    session_id=fixture.session_id,
                    kind=ArtifactKind.PROPOSITION,
                    ref_id=proposition_id,
                    label="Proposition",
                )
            )

        turn_id = uuid4()
        command = _agent_turn_commit(
            fixture,
            proposition_id,
            turn_id=turn_id,
            target_content_hash=proposition.content_hash,
        )

        async def commit_once() -> tuple[ArtifactWriteResult, ...]:
            async with database.session(fixture.workspace_id) as session:
                return await AgentProposalCommitter(
                    SqlAlchemyReasoningArtifactStore(session),
                    SqlAlchemyReasoningGraphStore(session),
                    SqlAlchemyReasoningLedger(session),
                ).commit(command)

        gathered = await asyncio.gather(commit_once(), commit_once())
        first, retry = tuple(gathered)
        assert retry == first
        assert len(first) == 1

        artifact_id = agent_turn_commit_id(turn_id, 0, "artifact")
        async with engine.connect() as connection:
            artifact = (
                await connection.execute(
                    text(
                        "SELECT kind, owner_actor_class, owner_actor_id, payload, metadata "
                        "FROM reasoning_artifacts WHERE id = :id"
                    ),
                    {"id": artifact_id},
                )
            ).one()
            assert tuple(artifact[:3]) == ("POSITION", "AGENT", fixture.agent_id)
            assert artifact.payload["evidence_ids"] == []
            assert artifact.metadata["evidence_disposition"] == "NO_EVIDENCE"
            assert artifact.metadata["attribution"]["turn_id"] == str(turn_id)
            assert artifact.metadata["attribution"]["model"] == "integration-model"
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM graph_nodes WHERE ref_id = :id"),
                    {"id": artifact_id},
                )
                == 1
            )
            event = (
                await connection.execute(
                    text(
                        "SELECT actor_class, actor_id, payload FROM reasoning_events WHERE id = :id"
                    ),
                    {"id": agent_turn_commit_id(turn_id, 0, "event")},
                )
            ).one()
            assert tuple(event[:2]) == ("AGENT", fixture.agent_id)
            assert event.payload["evidence_disposition"] == "NO_EVIDENCE"
            before = (
                await connection.scalar(
                    text("SELECT count(*) FROM reasoning_artifacts WHERE session_id = :id"),
                    {"id": fixture.session_id},
                ),
                await connection.scalar(
                    text("SELECT count(*) FROM graph_nodes WHERE session_id = :id"),
                    {"id": fixture.session_id},
                ),
                await connection.scalar(
                    text("SELECT count(*) FROM reasoning_events WHERE session_id = :id"),
                    {"id": fixture.session_id},
                ),
                await connection.scalar(
                    text("SELECT next_seq FROM session_ledger_heads WHERE session_id = :id"),
                    {"id": fixture.session_id},
                ),
            )

        fabricated_turn = uuid4()
        with pytest.raises(ArtifactCommitError, match="does not exist"):
            async with database.session(fixture.workspace_id) as session:
                await AgentProposalCommitter(
                    SqlAlchemyReasoningArtifactStore(session),
                    SqlAlchemyReasoningGraphStore(session),
                    SqlAlchemyReasoningLedger(session),
                ).commit(_agent_turn_commit(fixture, uuid4(), turn_id=fabricated_turn))

        async with engine.connect() as connection:
            after = (
                await connection.scalar(
                    text("SELECT count(*) FROM reasoning_artifacts WHERE session_id = :id"),
                    {"id": fixture.session_id},
                ),
                await connection.scalar(
                    text("SELECT count(*) FROM graph_nodes WHERE session_id = :id"),
                    {"id": fixture.session_id},
                ),
                await connection.scalar(
                    text("SELECT count(*) FROM reasoning_events WHERE session_id = :id"),
                    {"id": fixture.session_id},
                ),
                await connection.scalar(
                    text("SELECT next_seq FROM session_ledger_heads WHERE session_id = :id"),
                    {"id": fixture.session_id},
                ),
            )
            assert after == before
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM reasoning_artifacts WHERE id = :id"),
                    {"id": agent_turn_commit_id(fabricated_turn, 0, "artifact")},
                )
                == 0
            )


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_ledger_append_retry_read_verify_and_rollback() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "ledger-basic")
            assert (
                await connection.scalar(
                    text(
                        "SELECT next_seq FROM session_ledger_heads WHERE session_id = :session_id"
                    ),
                    {"session_id": fixture.session_id},
                )
                == 1
            )

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        event_id = uuid4()
        request = _ledger_append(fixture, event_id, "committed")
        async with sessions.begin() as session:
            ledger = SqlAlchemyReasoningLedger(session)
            first = await ledger.append(request)
            retry = await ledger.append(request)
            assert retry == first

        async with sessions.begin() as session:
            ledger = SqlAlchemyReasoningLedger(session)
            rows = await ledger.read(fixture.workspace_id, fixture.session_id)
            verification = await ledger.verify(fixture.workspace_id, fixture.session_id)
            retry_after_commit = await ledger.append(
                request.model_copy(update={"recorded_at": datetime(2030, 1, 1, tzinfo=UTC)})
            )
            assert rows == (first,)
            assert retry_after_commit == first
            assert verification.valid is True
            assert (verification.event_count, verification.head_hash) == (1, first.event_hash)

        with pytest.raises(LedgerIntegrityError, match="different caller values"):
            async with sessions.begin() as session:
                await SqlAlchemyReasoningLedger(session).append(
                    request.model_copy(update={"event_type": "STATUS_CHANGED"})
                )

        rolled_back_id = uuid4()
        with pytest.raises(RuntimeError, match="force rollback"):
            await _append_then_rollback(sessions, fixture, rolled_back_id)

        async with sessions.begin() as session:
            after_rollback = await SqlAlchemyReasoningLedger(session).append(
                _ledger_append(fixture, uuid4(), "after-rollback")
            )
            assert after_rollback.ledger_seq == 2


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_concurrent_ledger_appends_are_gapless_and_chain_verifies() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "ledger-concurrent")
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def append_one(index: int) -> None:
            async with sessions.begin() as session:
                await SqlAlchemyReasoningLedger(session).append(
                    _ledger_append(fixture, uuid4(), f"event-{index}")
                )

        await asyncio.gather(*(append_one(index) for index in range(8)))

        async with sessions.begin() as session:
            ledger = SqlAlchemyReasoningLedger(session)
            rows = await ledger.read(fixture.workspace_id, fixture.session_id)
            assert [event.ledger_seq for event in rows] == list(range(1, 9))
            assert all(rows[index].prev_hash == rows[index - 1].event_hash for index in range(1, 8))
            assert (await ledger.verify(fixture.workspace_id, fixture.session_id)).valid is True


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_ledger_detects_tampering_and_database_rejects_mutation() -> None:
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "ledger-tamper")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            event = await SqlAlchemyReasoningLedger(session).append(
                _ledger_append(fixture, uuid4(), "immutable")
            )

        for statement in (
            "UPDATE reasoning_events SET payload = '{\"tampered\": true}'::jsonb WHERE id = :id",
            "DELETE FROM reasoning_events WHERE id = :id",
        ):
            with pytest.raises(DBAPIError, match="reasoning events are append-only") as mutation:
                async with engine.begin() as connection:
                    await connection.execute(text(statement), {"id": event.id})
            assert getattr(mutation.value.orig, "sqlstate", None) == "27000"

        async with engine.begin() as connection:
            await connection.execute(text("ALTER TABLE reasoning_events DISABLE TRIGGER USER"))
            await connection.execute(
                text(
                    "UPDATE reasoning_events SET payload = "
                    "'{\"tampered\": true}'::jsonb WHERE id = :id"
                ),
                {"id": event.id},
            )
            await connection.execute(text("ALTER TABLE reasoning_events ENABLE TRIGGER USER"))
        async with sessions.begin() as session:
            verification = await SqlAlchemyReasoningLedger(session).verify(
                fixture.workspace_id, fixture.session_id
            )
            assert (verification.valid, verification.first_invalid_seq, verification.reason) == (
                False,
                1,
                "payload hash mismatch",
            )


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_forced_rls_isolates_ledger_tables() -> None:
    role = "agora_t305_app"
    async with _migrated_database() as engine:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            first = await _insert_session_graph(connection, "ledger-rls-a")
            second = await _insert_session_graph(connection, "ledger-rls-b")
        for fixture in (first, second):
            async with sessions.begin() as session:
                await SqlAlchemyReasoningLedger(session).append(
                    _ledger_append(fixture, uuid4(), "tenant event")
                )
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
            await connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await connection.execute(text(f"GRANT SELECT ON {', '.join(_LEDGER_TABLES)} TO {role}"))
            await connection.execute(text(f"GRANT INSERT ON reasoning_events TO {role}"))
            await connection.execute(text(f"GRANT UPDATE ON session_ledger_heads TO {role}"))
            assert (
                await connection.scalar(
                    text("SELECT has_table_privilege(:role, 'reasoning_events', 'UPDATE')"),
                    {"role": role},
                )
                is False
            )
            assert (
                await connection.scalar(
                    text("SELECT has_table_privilege(:role, 'reasoning_events', 'DELETE')"),
                    {"role": role},
                )
                is False
            )
            rows = await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = ANY(:tables) ORDER BY relname"
                ),
                {"tables": list(_LEDGER_TABLES)},
            )
            assert [tuple(row) for row in rows] == [
                (name, True, True) for name in sorted(_LEDGER_TABLES)
            ]
        async with engine.begin() as connection:
            await connection.execute(text(f"SET ROLE {role}"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(first.workspace_id)},
            )
            assert await connection.scalar(text("SELECT count(*) FROM reasoning_events")) == 1
            assert await connection.scalar(text("SELECT count(*) FROM session_ledger_heads")) == 1
        async with engine.begin() as connection:
            await connection.execute(text("RESET ROLE"))
            await connection.execute(text(f"DROP OWNED BY {role}"))
            await connection.execute(text(f"DROP ROLE {role}"))


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_lifecycle_transition_and_ledger_append_are_atomic_idempotent_and_rls_safe() -> None:
    role = "agora_t402_app"
    async with _migrated_database() as engine:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            first = await _insert_session_graph(connection, "lifecycle-a")
            second = await _insert_session_graph(connection, "lifecycle-b")

        for fixture in (first, second):
            async with sessions.begin() as session:
                ledger = SqlAlchemyReasoningLedger(session)
                await SqlAlchemySessionLifecycleStore(session, ledger).add_draft(
                    fixture.workspace_id,
                    fixture.session_id,
                    created_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
                )

        initialized_id = uuid4()
        initialized = SessionTransition(
            source=SessionLifecycleState.DRAFT,
            target=SessionLifecycleState.INITIALIZING,
            round=0,
            event=_ledger_append(first, initialized_id, "initialized").model_copy(
                update={
                    "event_type": "SESSION_INITIALIZED",
                    "payload": {"from": "DRAFT", "to": "INITIALIZING"},
                    "recorded_at": datetime(2026, 9, 5, 13, tzinfo=UTC),
                }
            ),
        )
        async with sessions.begin() as session:
            ledger = SqlAlchemyReasoningLedger(session)
            store = SqlAlchemySessionLifecycleStore(session, ledger)
            committed = await store.transition(initialized)
            replay = await store.transition(initialized)
            assert committed == replay
        assert [event.id for event in ledger.appended] == [initialized_id]

        # Temporal may lose the activity acknowledgement after PostgreSQL commits. A
        # replacement worker receives the same event identity and must observe the
        # checkpoint without creating another transport publication candidate.
        async with sessions.begin() as session:
            retry_ledger = SqlAlchemyReasoningLedger(session)
            retried = await SqlAlchemySessionLifecycleStore(session, retry_ledger).transition(
                initialized
            )
            assert retried == committed
            assert retry_ledger.appended == []

        started_id = uuid4()
        started = SessionTransition(
            source=SessionLifecycleState.INITIALIZING,
            target=SessionLifecycleState.RUNNING,
            round=1,
            event=_ledger_append(first, started_id, "round started").model_copy(
                update={
                    "event_type": "ROUND_STARTED",
                    "causation_id": initialized_id,
                    "round": 1,
                    "payload": {"from": "INITIALIZING", "to": "RUNNING"},
                    "recorded_at": datetime(2026, 9, 5, 13, 30, tzinfo=UTC),
                }
            ),
        )
        async with sessions.begin() as session:
            ledger = SqlAlchemyReasoningLedger(session)
            store = SqlAlchemySessionLifecycleStore(session, ledger)
            running = await store.transition(started)
            replay = await store.transition(started)
            assert running == replay
            assert running.state is SessionLifecycleState.RUNNING
            assert running.round == 1
            assert running.last_event_id == started_id

        failed = SessionTransition(
            source=SessionLifecycleState.RUNNING,
            target=SessionLifecycleState.FAILED,
            round=1,
            event=_ledger_append(first, uuid4(), "failed").model_copy(
                update={
                    "event_type": "SESSION_FAILED",
                    "round": 1,
                    "payload": {"from": "RUNNING", "to": "FAILED"},
                    "recorded_at": datetime(2026, 9, 5, 14, tzinfo=UTC),
                }
            ),
        )

        async def rolled_back_transition() -> None:
            async with sessions.begin() as session:
                ledger = SqlAlchemyReasoningLedger(session)
                await SqlAlchemySessionLifecycleStore(session, ledger).transition(failed)
                raise RuntimeError("force rollback")

        with pytest.raises(RuntimeError, match="force rollback"):
            await rolled_back_transition()

        async with sessions.begin() as session:
            lifecycle = await SqlAlchemySessionLifecycleStore(
                session, SqlAlchemyReasoningLedger(session)
            ).get(first.workspace_id, first.session_id)
            assert lifecycle is not None
            assert lifecycle.state is SessionLifecycleState.RUNNING
            assert lifecycle.round == 1
            assert lifecycle.last_event_id == started_id
            assert (
                len(
                    await SqlAlchemyReasoningLedger(session).read(
                        first.workspace_id, first.session_id
                    )
                )
                == 2
            )

        dead_letter_id = uuid4()
        dead_lettered_at = datetime(2026, 9, 5, 14, 30, tzinfo=UTC)
        dead_letter_payload = {
            "from": "DRAFT",
            "to": "FAILED",
            "failure": {
                "activity_type": "commit_session_bootstrap_transition",
                "operation_id": (
                    f"{second.session_id}:commit_session_bootstrap_transition:{uuid4()}"
                ),
                "retry_state": "MAXIMUM_ATTEMPTS_REACHED",
                "termination_reason": "ACTIVITY_POLICY_EXHAUSTED",
            },
        }
        dead_letter = SessionTransition(
            source=SessionLifecycleState.DRAFT,
            target=SessionLifecycleState.FAILED,
            round=0,
            event=_ledger_append(second, dead_letter_id, "dead letter").model_copy(
                update={
                    "event_type": "ACTIVITY_DEAD_LETTERED",
                    "actor_class": ActorClass.SERVICE,
                    "payload": dead_letter_payload,
                    "recorded_at": dead_lettered_at,
                }
            ),
        )
        async with sessions.begin() as session:
            ledger = SqlAlchemyReasoningLedger(session)
            store = SqlAlchemySessionLifecycleStore(session, ledger)
            failed_draft = await store.transition(dead_letter)
            replay = await store.transition(dead_letter)
            events = await ledger.read(second.workspace_id, second.session_id)

        assert replay == failed_draft
        assert failed_draft.state is SessionLifecycleState.FAILED
        assert failed_draft.round == 0
        assert failed_draft.last_event_id == dead_letter_id
        assert failed_draft.initialized_at == dead_lettered_at
        assert failed_draft.started_at == dead_lettered_at
        assert failed_draft.ended_at == dead_lettered_at
        assert len(events) == 1
        assert events[0].id == dead_letter_id
        assert events[0].event_type == "ACTIVITY_DEAD_LETTERED"
        assert events[0].payload == dead_letter_payload

        async with engine.begin() as connection:
            await connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
            await connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await connection.execute(text(f"GRANT SELECT ON session_lifecycles TO {role}"))
            flags = tuple(
                (
                    await connection.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                            "WHERE relname = 'session_lifecycles'"
                        )
                    )
                ).one()
            )
            assert flags == (True, True)

        async with engine.begin() as connection:
            await connection.execute(text(f"SET ROLE {role}"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(first.workspace_id)},
            )
            assert await connection.scalar(text("SELECT count(*) FROM session_lifecycles")) == 1

        async with engine.begin() as connection:
            await connection.execute(text("RESET ROLE"))
            await connection.execute(text(f"DROP OWNED BY {role}"))
            await connection.execute(text(f"DROP ROLE {role}"))


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_committed_transition_wakes_sse_but_replays_from_postgres_ledger() -> None:
    nats_url = os.getenv("TEST_NATS_URL")
    if not nats_url:
        pytest.skip("TEST_NATS_URL is not configured")
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            fixture = await _insert_session_graph(connection, "realtime-live")

        database = Database(engine)
        async with database.session(fixture.workspace_id) as session:
            ledger = SqlAlchemyReasoningLedger(session)
            await SqlAlchemySessionLifecycleStore(session, ledger).add_draft(
                fixture.workspace_id,
                fixture.session_id,
                created_at=datetime.now(UTC),
            )

        bus = NatsJetStreamEventBus(
            nats_url,
            stream=os.getenv("TEST_NATS_STREAM", "AGORA"),
        )
        gateway = RealtimeGateway(database, bus, code_version="integration")
        try:
            await bus.connect()
            await gateway.start()
            stream = cast(
                AsyncGenerator[bytes, None],
                gateway.stream(
                    fixture.workspace_id,
                    fixture.session_id,
                    after=0,
                    heartbeat_s=5.0,
                ),
            )
            pending_frame = asyncio.create_task(anext(stream))
            await asyncio.sleep(0.1)

            event_id = uuid4()
            await SqlAlchemySessionTransitionCommitter(
                database,
                service_actor_id=fixture.user_id,
                event_bus=bus,
                code_version="integration",
            ).commit(
                SessionBootstrapTransition(
                    workspace_id=fixture.workspace_id,
                    session_id=fixture.session_id,
                    event_id=event_id,
                    event_type="SESSION_INITIALIZED",
                    source=SessionLifecycleState.DRAFT,
                    target=SessionLifecycleState.INITIALIZING,
                    round=0,
                    correlation_id=uuid4(),
                )
            )

            frame = await asyncio.wait_for(pending_frame, timeout=5.0)
            assert frame.startswith(b"id: 1\nevent: SESSION_INITIALIZED")
            assert f'"event_id":"{event_id}"'.encode() in frame
            async with database.session(fixture.workspace_id) as session:
                persisted = await SqlAlchemyReasoningLedger(session).read(
                    fixture.workspace_id, fixture.session_id
                )
            assert [event.id for event in persisted] == [event_id]
            await stream.aclose()
        finally:
            await bus.close()


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_forced_rls_isolates_every_phase_3_table() -> None:
    role = "agora_t303_app"
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            first = await _insert_session_graph(connection, "rls-a")
            second = await _insert_session_graph(connection, "rls-b")
            await connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
            await connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await connection.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(_PHASE_3_TABLES)} "
                    f"TO {role}"
                )
            )
            rls_rows = [
                tuple(row)
                for row in (
                    await connection.execute(
                        text(
                            "SELECT relname, relrowsecurity, relforcerowsecurity "
                            "FROM pg_class WHERE relname = ANY(:tables) ORDER BY relname"
                        ),
                        {"tables": list(_PHASE_3_TABLES)},
                    )
                ).all()
            ]
            assert rls_rows == [(name, True, True) for name in sorted(_PHASE_3_TABLES)]

        async with engine.begin() as connection:
            await connection.execute(text(f"SET ROLE {role}"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(first.workspace_id)},
            )
            expected_counts = {
                "reasoning_artifacts": 2,
                "session_agents": 1,
                "session_constraints": 1,
                "session_objectives": 1,
                "sessions": 1,
            }
            for table, expected in expected_counts.items():
                assert await connection.scalar(text(f"SELECT count(*) FROM {table}")) == expected
            result = await connection.execute(
                text("UPDATE sessions SET problem_statement = 'hidden' WHERE id = :id"),
                {"id": second.session_id},
            )
            assert result.rowcount == 0

        with pytest.raises(DBAPIError, match="row-level security policy") as cross_tenant_insert:
            await _insert_session_as_role(
                engine,
                role=role,
                current_workspace_id=second.workspace_id,
                row_workspace_id=first.workspace_id,
                created_by=first.user_id,
            )
        assert getattr(cross_tenant_insert.value.orig, "sqlstate", None) == "42501"


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_api_idempotency_is_durable_and_forced_rls_isolated() -> None:
    role = "agora_t307_app"
    async with _migrated_database() as engine:
        async with engine.begin() as connection:
            first_workspace, _, _ = await _insert_tenant(connection, "api-idempotency-a")
            second_workspace, _, _ = await _insert_tenant(connection, "api-idempotency-b")

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        expected = IdempotencyRecord(
            request_hash=f"sha256:{'a' * 64}",
            status_code=201,
            response_body={"data": {"id": "art_example"}, "meta": {"version": 1}},
        )
        async with sessions.begin() as session:
            await session.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(first_workspace)},
            )
            store = SqlAlchemyIdempotencyStore(session)
            assert (
                await store.load_after_lock(first_workspace, "artifact:create", "retry-key") is None
            )
            await store.save(first_workspace, "artifact:create", "retry-key", expected)

        async with sessions.begin() as session:
            await session.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(first_workspace)},
            )
            assert (
                await SqlAlchemyIdempotencyStore(session).load_after_lock(
                    first_workspace, "artifact:create", "retry-key"
                )
                == expected
            )

        async with engine.begin() as connection:
            await connection.execute(text(f"DROP ROLE IF EXISTS {role}"))
            await connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await connection.execute(
                text(f"GRANT SELECT, INSERT ON {', '.join(_API_TABLES)} TO {role}")
            )
            rows = await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = ANY(:tables) ORDER BY relname"
                ),
                {"tables": list(_API_TABLES)},
            )
            assert [tuple(row) for row in rows] == [
                (name, True, True) for name in sorted(_API_TABLES)
            ]

        async with engine.begin() as connection:
            await connection.execute(text(f"SET ROLE {role}"))
            await connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": str(first_workspace)},
            )
            assert (
                await connection.scalar(text("SELECT count(*) FROM api_idempotency_records")) == 1
            )

        with pytest.raises(DBAPIError, match="row-level security policy") as cross_tenant:
            await _insert_idempotency_as_role(
                engine,
                role=role,
                current_workspace_id=first_workspace,
                row_workspace_id=second_workspace,
            )
        assert getattr(cross_tenant.value.orig, "sqlstate", None) == "42501"


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_reasoning_revision_downgrades_reupgrades_and_has_no_drift() -> None:
    config = _alembic_config()
    async with _migrated_database() as engine:
        await asyncio.to_thread(command.downgrade, config, "20260905_0004")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260905_0004"
            )
            for table in _PHASE_3_TABLES:
                assert (
                    await connection.scalar(text("SELECT to_regclass(:table)"), {"table": table})
                    is None
                )
            phase_2_tables = set(
                await connection.scalars(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            )

        await asyncio.to_thread(command.upgrade, config, "20260905_0005")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260905_0005"
            )
            for table in _PHASE_3_TABLES:
                assert (
                    await connection.scalar(text("SELECT to_regclass(:table)"), {"table": table})
                    == table
                )
            phase_3_tables = set(
                await connection.scalars(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            )
            assert phase_3_tables - phase_2_tables == set(_PHASE_3_TABLES)

        await asyncio.to_thread(command.upgrade, config, "20260905_0006")
        async with engine.begin() as connection:
            existing = await _insert_session_graph(connection, "ledger-backfill")

        await asyncio.to_thread(command.upgrade, config, "head")
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                ScriptDirectory.from_config(config).get_current_head()
            )
            for table in _GRAPH_TABLES:
                assert (
                    await connection.scalar(text("SELECT to_regclass(:table)"), {"table": table})
                    == table
                )
            for table in _LEDGER_TABLES:
                assert (
                    await connection.scalar(text("SELECT to_regclass(:table)"), {"table": table})
                    == table
                )
            for table in _API_TABLES:
                assert (
                    await connection.scalar(text("SELECT to_regclass(:table)"), {"table": table})
                    == table
                )
            for table in _PHASE_4_TABLES:
                assert (
                    await connection.scalar(text("SELECT to_regclass(:table)"), {"table": table})
                    == table
                )
            for table in _PHASE_5_TABLES:
                assert (
                    await connection.scalar(text("SELECT to_regclass(:table)"), {"table": table})
                    == table
                )
            for table in _PHASE_6_TABLES:
                assert (
                    await connection.scalar(text("SELECT to_regclass(:table)"), {"table": table})
                    == table
                )
            for table in (*_PHASE_7_TABLES, *_PHASE_8_TABLES):
                assert (
                    await connection.scalar(text("SELECT to_regclass(:table)"), {"table": table})
                    == table
                )
            assert (
                await connection.scalar(
                    text(
                        "SELECT next_seq FROM session_ledger_heads WHERE session_id = :session_id"
                    ),
                    {"session_id": existing.session_id},
                )
                == 1
            )
            head_tables = set(
                await connection.scalars(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            )
            assert head_tables - phase_2_tables == {
                *_ALL_PHASE_3_TABLES,
                *_PHASE_4_TABLES,
                *_PHASE_5_TABLES,
                *_PHASE_6_TABLES,
                *_PHASE_7_TABLES,
                *_PHASE_8_TABLES,
                *_PHASE_10_TABLES,
                *_PHASE_11_TABLES,
                *_PHASE_12_TABLES,
                *_PHASE_13_TABLES,
            }
        await asyncio.to_thread(command.check, config)


@req("FR-102", "FR-210", "FR-302", "FR-303", "FR-312", "FR-503")
async def test_phase3_database_schema_matches_documented_manifest() -> None:
    async with _migrated_database() as engine, engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT table_name, column_name, "
                    "CASE WHEN data_type = 'numeric' "
                    "THEN format('numeric(%s,%s)', numeric_precision, numeric_scale) "
                    "ELSE data_type END || "
                    "CASE is_nullable WHEN 'YES' THEN ' NULL' "
                    "ELSE ' NOT NULL' END AS signature "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = ANY(:tables) "
                    "ORDER BY table_name, ordinal_position"
                ),
                {"tables": list(_ALL_PHASE_3_TABLES)},
            )
        ).all()

    actual: dict[str, dict[str, str]] = {}
    for table_name, column_name, signature in rows:
        actual.setdefault(table_name, {})[column_name] = signature

    expected = {
        table_name: columns
        for revision in _PHASE_3_REVISIONS
        for table_name, columns in _PHASE_3_SCHEMA[revision].items()
    }
    assert set(actual) == set(expected)
    for table_name, expected_columns in expected.items():
        assert list(actual[table_name].items()) == list(expected_columns.items()), table_name
