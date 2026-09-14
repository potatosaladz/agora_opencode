"""Live PostgreSQL proof for validated semantic memory history (FR-405, FR-406)."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db.memory import SqlAlchemyMemoryProvider
from app.db.reasoning_artifacts import SqlAlchemyReasoningArtifactStore
from app.db.session import Database
from app.domain.memory import (
    ArtifactRef,
    MemoryQuery,
    MemoryScope,
    MemoryState,
    MemoryTier,
    RetentionPolicy,
    ValidationRecord,
)
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    Bearing,
    ClaimPayload,
    ClaimType,
    EvidencePayload,
    EvidenceProvenance,
    EvidenceRelation,
    LifecycleStatus,
    Provenance,
    ProvenanceOrigin,
    ReasoningArtifact,
    ReviewStatus,
    SourceReference,
    Strength,
    TrustLevel,
    Verification,
    artifact_content_hash,
    validate_artifact,
)
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL not configured"),
]
NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


def _artifact(
    workspace: UUID, session: UUID, user: UUID, kind: ArtifactKind, payload: object
) -> ReasoningArtifact:
    values = {
        "id": uuid4(),
        "workspace_id": workspace,
        "session_id": session,
        "logical_id": uuid4(),
        "kind": kind,
        "schema_version": 1,
        "version": 1,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": None,
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": user,
        "round": 0,
        "payload": payload,
        "provenance": Provenance(origin=ProvenanceOrigin.HUMAN, reference="memory validation"),
        "source_references": (
            SourceReference(
                reference="validation record",
                locator={"char_start": 0, "char_end": 10},
                content_hash=HASH,
                retrieved_at=NOW,
                source_timestamp=NOW,
            ),
        )
        if kind is ArtifactKind.EVIDENCE
        else (),
        "parent_relationships": (),
        "confidence": None,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    values["content_hash"] = artifact_content_hash(values)
    return validate_artifact(values)


async def _insert_promotion_without_evidence(
    engine: AsyncEngine,
    *,
    entry_id: UUID,
    promotion_id: UUID,
    workspace_id: UUID,
    namespace_id: UUID,
    session_id: UUID,
    artifact_id: UUID,
    validator_id: UUID,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO semantic_memory_entries "
                "(id, workspace_id, namespace_id, source_session_id, source_artifact_id, "
                "source_artifact_kind, source_content_hash, version, promoted_at) VALUES "
                "(:id, :workspace, :namespace, :session, :artifact, "
                "'OBJECTIVE', :hash, 1, :now)"
            ),
            {
                "id": entry_id,
                "workspace": workspace_id,
                "namespace": namespace_id,
                "session": session_id,
                "artifact": artifact_id,
                "hash": "sha256:" + "f" * 64,
                "now": NOW,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO memory_promotions "
                "(id, workspace_id, entry_id, validator_id, justification, caveats, "
                "promoted_at) VALUES "
                "(:id, :workspace, :entry, :validator, 'checked', ARRAY['scope'], :now)"
            ),
            {
                "id": promotion_id,
                "workspace": workspace_id,
                "entry": entry_id,
                "validator": validator_id,
                "now": NOW,
            },
        )


@req("FR-406")
async def test_validated_promotion_and_additive_retention_history() -> None:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(command.upgrade, config, "head")

    workspace, user, session, namespace, agent, objective = (uuid4() for _ in range(6))
    async with engine.begin() as connection:
        await connection.execute(text("DROP ROLE IF EXISTS agora_t508_app"))
        await connection.execute(text("CREATE ROLE agora_t508_app NOLOGIN"))
        await connection.execute(text("GRANT USAGE ON SCHEMA public TO agora_t508_app"))
        await connection.execute(
            text(
                "GRANT SELECT, INSERT ON semantic_memory_entries, memory_promotions, "
                "memory_promotion_evidence, memory_lifecycle_events TO agora_t508_app"
            )
        )
        await connection.execute(
            text("INSERT INTO workspaces (id, slug, name) VALUES (:id, :slug, 'T5-08')"),
            {"id": workspace, "slug": f"t508-{workspace.hex}"},
        )
        await connection.execute(
            text(
                "INSERT INTO users (id, oidc_issuer, oidc_subject, display_name) "
                "VALUES (:id, 'fixture', :subject, 'Validator')"
            ),
            {"id": user, "subject": str(user)},
        )
        await connection.execute(
            text(
                "INSERT INTO workspace_members (workspace_id, user_id, role) "
                "VALUES (:workspace, :user, 'RESEARCHER')"
            ),
            {"workspace": workspace, "user": user},
        )
        await connection.execute(
            text(
                "INSERT INTO agent_definitions (id, workspace_id, logical_id, version, name, "
                "domain, role_kind, knowledge_ns, strategy_ref, strategy_ver, prompt_ref, "
                "prompt_hash, status) VALUES (:id, :workspace, :logical, 1, 'Memory Agent', "
                "'testing', 'domain_expert', '{}'::uuid[], 'strategy/test', '1', "
                "'prompt/test', 'sha256:test', 'ACTIVE')"
            ),
            {"id": agent, "workspace": workspace, "logical": uuid4()},
        )
        await connection.execute(
            text(
                "INSERT INTO sessions (id, workspace_id, problem_statement, max_rounds, "
                "budget_tokens, budget_usd, created_by) "
                "VALUES (:id, :workspace, 'Memory test', 2, 1000, 10, :user)"
            ),
            {"id": session, "workspace": workspace, "user": user},
        )
        await connection.execute(
            text(
                "INSERT INTO session_agents (workspace_id, session_id, agent_def_id) "
                "VALUES (:workspace, :session, :agent)"
            ),
            {"workspace": workspace, "session": session, "agent": agent},
        )
        await connection.execute(
            text(
                "INSERT INTO reasoning_artifacts (id, workspace_id, session_id, logical_id, "
                "kind, schema_version, version, status, owner_actor_class, owner_actor_id, "
                "round, payload, provenance, source_references, parent_relationships, "
                "metadata, content_hash, created_at, updated_at) VALUES (:id, :workspace, "
                ":session, :logical, 'OBJECTIVE', 1, 1, 'ACTIVE', 'HUMAN', :user, 0, "
                "CAST(:payload AS jsonb), CAST(:provenance AS jsonb), '[]'::jsonb, "
                "'[]'::jsonb, '{}'::jsonb, :hash, :now, :now)"
            ),
            {
                "id": objective,
                "workspace": workspace,
                "session": session,
                "logical": uuid4(),
                "user": user,
                "payload": (
                    '{"name":"Memory integrity","objective_type":"UTILITY",'
                    '"direction":"MAXIMIZE","weight":"1",'
                    '"weight_rationale":"T5-08 fixture","time_horizon":"test",'
                    '"conflicts_with_ids":[]}'
                ),
                "provenance": '{"origin":"HUMAN","reference":"integration-test"}',
                "hash": "sha256:" + "f" * 64,
                "now": NOW,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO session_objectives (workspace_id, session_id, artifact_id) "
                "VALUES (:workspace, :session, :objective)"
            ),
            {"workspace": workspace, "session": session, "objective": objective},
        )
        await connection.execute(
            text(
                "INSERT INTO knowledge_namespaces (id, workspace_id, tier, name) "
                "VALUES (:id, :workspace, 'HISTORICAL', 'validated history')"
            ),
            {"id": namespace, "workspace": workspace},
        )

    claim = _artifact(
        workspace,
        session,
        user,
        ArtifactKind.CLAIM,
        ClaimPayload(
            statement="Validated historical claim",
            claim_type=ClaimType.FACTUAL,
            direction=Bearing.SUPPORTS,
            strength=Strength.MODERATE,
            supporting_evidence_ids=(),
            opposing_evidence_ids=(),
            review_status=ReviewStatus.PROPOSED,
        ),
    )
    evidence = _artifact(
        workspace,
        session,
        user,
        ArtifactKind.EVIDENCE,
        EvidencePayload(
            claim_id=claim.id,
            relation=EvidenceRelation.SUPPORTS,
            quote="validation",
            verification=Verification.UNVERIFIED,
            trust_level=TrustLevel.PRIMARY,
            weight="0",
            provenance_kind=EvidenceProvenance.HUMAN,
        ),
    )
    scope = MemoryScope(workspace_id=workspace, tier=MemoryTier.SEMANTIC, namespace_id=namespace)
    source = ArtifactRef(
        entry_id=uuid4(),
        promotion_id=uuid4(),
        workspace_id=workspace,
        session_id=session,
        artifact_id=claim.id,
    )
    database = Database(engine)
    async with database.session(workspace) as db_session:
        artifacts = SqlAlchemyReasoningArtifactStore(db_session)
        await artifacts.add(claim)
        await artifacts.add(evidence)
        memory = SqlAlchemyMemoryProvider(db_session)
        promoted = await memory.promote(
            source,
            scope,
            ValidationRecord(
                validator_id=user,
                evidence_artifact_ids=(evidence.id,),
                justification="human checked cited evidence",
                caveats=("review after policy update",),
                validated_at=NOW,
                review_by=NOW + timedelta(days=1),
            ),
        )
        assert promoted.version == 1
        active = await memory.read(scope, MemoryQuery(entry_id=source.entry_id, as_of=NOW))
        assert active.entries[0].state is MemoryState.ACTIVE
        stale = await memory.read(
            scope, MemoryQuery(entry_id=source.entry_id, as_of=NOW + timedelta(days=2))
        )
        assert stale.entries[0].state is MemoryState.STALE
        assert (
            await memory.expire(
                scope,
                RetentionPolicy(
                    event_id=uuid4(),
                    entry_id=source.entry_id,
                    state=MemoryState.STALE,
                    actor_id=user,
                    reason="review window elapsed",
                    recorded_at=NOW + timedelta(hours=12),
                ),
            )
            == 1
        )
        assert (
            await memory.expire(
                scope,
                RetentionPolicy(
                    event_id=uuid4(),
                    entry_id=source.entry_id,
                    state=MemoryState.ARCHIVED,
                    actor_id=user,
                    reason="retention archive",
                    recorded_at=NOW + timedelta(days=3),
                ),
            )
            == 1
        )

    async with engine.begin() as connection:
        counts = (
            await connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM semantic_memory_entries), "
                    "(SELECT count(*) FROM memory_promotions), "
                    "(SELECT count(*) FROM memory_promotion_evidence), "
                    "(SELECT count(*) FROM memory_lifecycle_events)"
                )
            )
        ).one()
        assert counts == (1, 1, 1, 2)
        forced = set(
            (
                await connection.execute(
                    text(
                        "SELECT relname FROM pg_class WHERE relname = ANY(:tables) "
                        "AND relrowsecurity AND relforcerowsecurity"
                    ),
                    {
                        "tables": [
                            "semantic_memory_entries",
                            "memory_promotions",
                            "memory_promotion_evidence",
                            "memory_lifecycle_events",
                        ]
                    },
                )
            ).scalars()
        )
        assert len(forced) == 4
    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL ROLE agora_t508_app"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(uuid4())},
        )
        assert await connection.scalar(text("SELECT count(*) FROM semantic_memory_entries")) == 0
    with pytest.raises(DBAPIError, match="requires validated promotion"):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO semantic_memory_entries "
                    "(id, workspace_id, namespace_id, source_session_id, source_artifact_id, "
                    "source_artifact_kind, source_content_hash, version, promoted_at) VALUES "
                    "(:id, :workspace, :namespace, :session, :artifact, 'EVIDENCE', :hash, 1, :now)"
                ),
                {
                    "id": uuid4(),
                    "workspace": workspace,
                    "namespace": namespace,
                    "session": session,
                    "artifact": evidence.id,
                    "hash": evidence.content_hash,
                    "now": NOW,
                },
            )
    no_evidence_entry, no_evidence_promotion = uuid4(), uuid4()
    with pytest.raises(DBAPIError, match="requires evidence"):
        await _insert_promotion_without_evidence(
            engine,
            entry_id=no_evidence_entry,
            promotion_id=no_evidence_promotion,
            workspace_id=workspace,
            namespace_id=namespace,
            session_id=session,
            artifact_id=objective,
            validator_id=user,
        )
    with pytest.raises(DBAPIError, match="append-only"):
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM semantic_memory_entries WHERE id = :id"),
                {"id": source.entry_id},
            )
    await asyncio.to_thread(command.check, config)
    await asyncio.to_thread(command.downgrade, config, "20260906_0015")
    async with engine.connect() as connection:
        assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260906_0015"
        )
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.check, config)
    async with engine.begin() as connection:
        await connection.execute(text("DROP OWNED BY agora_t508_app"))
        await connection.execute(text("DROP ROLE agora_t508_app"))
    await database.close()
