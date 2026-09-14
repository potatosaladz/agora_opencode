"""Live PostgreSQL proof for namespace-tier authorization and retrieval audit."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.retrieval.postgres import PostgresCandidateSearch
from app.application.retrieval import HybridRetriever, NoopReranker
from app.db.retrieval import PostgresRetrievalAudit
from app.domain.knowledge import NamespaceSubjectKind
from app.domain.retrieval import PrincipalClass, RetrievalRequest, RetrievalSubject
from app.ports.errors import PermanentPortError
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL not configured"),
]
_NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


def _request(
    workspace_id: UUID,
    principal_class: PrincipalClass,
    principal_id: UUID,
    namespace_ids: tuple[UUID, ...],
    subjects: tuple[RetrievalSubject, ...],
) -> RetrievalRequest:
    return RetrievalRequest(
        attempt_id=uuid4(),
        trace_id=uuid4(),
        workspace_id=workspace_id,
        principal_class=principal_class,
        principal_id=principal_id,
        namespace_ids=namespace_ids,
        subjects=subjects,
        query="authorization probe",
        query_vector=[0.0] * 1536,
        embedding_model="fixture-embed",
        embedding_version="1",
        index_version="fixture-index-1",
        requested_at=_NOW,
    )


@req("FR-405")
async def test_all_namespace_tiers_validate_principals_and_audit_denials() -> None:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(command.upgrade, config, "head")

    workspace, user, agent, unbound_agent, session = [uuid4() for _ in range(5)]
    objective = uuid4()
    tiers = ("GLOBAL", "WORKSPACE", "DOMAIN", "AGENT", "SESSION", "HISTORICAL")
    namespace_ids = {tier: uuid4() for tier in tiers}
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO workspaces (id, slug, name) VALUES (:id, :slug, 'T5-06')"),
            {"id": workspace, "slug": f"t506-{workspace.hex}"},
        )
        await connection.execute(
            text(
                "INSERT INTO users (id, oidc_issuer, oidc_subject, display_name) "
                "VALUES (:id, 'fixture', :subject, 'T5-06 User')"
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
        for agent_id, manifest in (
            (
                agent,
                [namespace_ids["DOMAIN"], namespace_ids["HISTORICAL"]],
            ),
            (unbound_agent, []),
        ):
            await connection.execute(
                text(
                    "INSERT INTO agent_definitions (id, workspace_id, logical_id, version, "
                    "name, domain, role_kind, knowledge_ns, strategy_ref, strategy_ver, "
                    "prompt_ref, prompt_hash, status) VALUES (:id, :workspace, :logical, 1, "
                    ":name, 'testing', 'domain_expert', CAST(:manifest AS uuid[]), "
                    "'strategy/test', '1', 'prompt/test', 'sha256:test', 'ACTIVE')"
                ),
                {
                    "id": agent_id,
                    "workspace": workspace,
                    "logical": uuid4(),
                    "name": f"agent-{agent_id}",
                    "manifest": manifest,
                },
            )
        await connection.execute(
            text(
                "INSERT INTO sessions (id, workspace_id, problem_statement, max_rounds, "
                "budget_tokens, budget_usd, created_by) "
                "VALUES (:id, :workspace, 'T5-06 session', 2, 1000, 10.00, :user)"
            ),
            {"id": session, "workspace": workspace, "user": user},
        )
        await connection.execute(
            text(
                "INSERT INTO session_lifecycles (session_id, workspace_id, state, round) "
                "VALUES (:session, :workspace, 'DRAFT', 0)"
            ),
            {"workspace": workspace, "session": session},
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
                "INSERT INTO reasoning_artifacts (id, workspace_id, session_id, logical_id, kind, "
                "schema_version, version, status, owner_actor_class, owner_actor_id, round, "
                "payload, provenance, source_references, parent_relationships, content_hash, "
                "created_at, updated_at) VALUES (:id, :workspace, :session, :logical, "
                "'OBJECTIVE', 1, 1, "
                "'ACTIVE', 'HUMAN', :user, 0, CAST(:payload AS jsonb), CAST(:provenance AS jsonb), "
                "'[]'::jsonb, '[]'::jsonb, :hash, :created_at, :created_at)"
            ),
            {
                "id": objective,
                "workspace": workspace,
                "session": session,
                "logical": uuid4(),
                "user": user,
                "payload": (
                    '{"name":"Authorize retrieval","objective_type":"UTILITY",'
                    '"direction":"MAXIMIZE","weight":"1",'
                    '"weight_rationale":"Authorization fixture",'
                    '"time_horizon":"test","conflicts_with_ids":[]}'
                ),
                "provenance": '{"origin":"HUMAN","reference":"integration-test"}',
                "hash": "sha256:" + "a" * 64,
                "created_at": _NOW,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO session_objectives "
                "(workspace_id, session_id, artifact_id) "
                "VALUES (:workspace, :session, :objective)"
            ),
            {"workspace": workspace, "session": session, "objective": objective},
        )
        for tier, namespace_id in namespace_ids.items():
            await connection.execute(
                text(
                    "INSERT INTO knowledge_namespaces "
                    "(id, workspace_id, tier, name, session_id, agent_def_id) "
                    "VALUES (:id, :workspace, :tier, :name, :session_id, :agent_id)"
                ),
                {
                    "id": namespace_id,
                    "workspace": workspace,
                    "tier": tier,
                    "name": f"{tier.lower()}-{namespace_id}",
                    "session_id": session if tier == "SESSION" else None,
                    "agent_id": agent if tier == "AGENT" else None,
                },
            )
        grants = [
            ("GLOBAL", "WORKSPACE", workspace),
            ("WORKSPACE", "WORKSPACE", workspace),
            ("DOMAIN", "AGENT_DEFINITION", agent),
            ("AGENT", "AGENT_DEFINITION", agent),
            ("SESSION", "SESSION", session),
            ("HISTORICAL", "AGENT_DEFINITION", agent),
        ]
        for tier, subject_kind, subject_id in grants:
            await connection.execute(
                text(
                    "INSERT INTO knowledge_namespace_grants "
                    "(id, workspace_id, namespace_id, subject_kind, subject_id, capability, "
                    "valid_from) VALUES (:id, :workspace, :namespace, :kind, :subject, "
                    "'READ', :valid_from)"
                ),
                {
                    "id": uuid4(),
                    "workspace": workspace,
                    "namespace": namespace_ids[tier],
                    "kind": subject_kind,
                    "subject": subject_id,
                    "valid_from": _NOW,
                },
            )

    search = PostgresCandidateSearch(engine, workspace)
    workspace_subject = RetrievalSubject(kind=NamespaceSubjectKind.WORKSPACE, id=workspace)
    user_subject = RetrievalSubject(kind=NamespaceSubjectKind.USER, id=user)
    agent_subject = RetrievalSubject(kind=NamespaceSubjectKind.AGENT_DEFINITION, id=agent)
    session_subject = RetrievalSubject(kind=NamespaceSubjectKind.SESSION, id=session)

    human = _request(
        workspace,
        PrincipalClass.HUMAN,
        user,
        (namespace_ids["GLOBAL"], namespace_ids["WORKSPACE"]),
        (workspace_subject, user_subject),
    )
    assert set(await search.authorize(human)) == {
        namespace_ids["GLOBAL"],
        namespace_ids["WORKSPACE"],
    }
    agent_request = _request(
        workspace,
        PrincipalClass.AGENT,
        agent,
        (namespace_ids["DOMAIN"], namespace_ids["AGENT"], namespace_ids["HISTORICAL"]),
        (workspace_subject, agent_subject),
    )
    assert set(await search.authorize(agent_request)) == {
        namespace_ids["DOMAIN"],
        namespace_ids["AGENT"],
        namespace_ids["HISTORICAL"],
    }
    human_session = _request(
        workspace,
        PrincipalClass.HUMAN,
        user,
        (namespace_ids["SESSION"],),
        (workspace_subject, user_subject, session_subject),
    )
    assert await search.authorize(human_session) == (namespace_ids["SESSION"],)
    agent_session = _request(
        workspace,
        PrincipalClass.AGENT,
        agent,
        (namespace_ids["SESSION"],),
        (workspace_subject, agent_subject, session_subject),
    )
    assert await search.authorize(agent_session) == (namespace_ids["SESSION"],)

    forged = human.model_copy(
        update={
            "attempt_id": uuid4(),
            "namespace_ids": (namespace_ids["GLOBAL"],),
            "subjects": (*human.subjects, agent_subject),
        }
    )
    assert await search.authorize(forged) == ()
    unbound_subject = RetrievalSubject(kind=NamespaceSubjectKind.AGENT_DEFINITION, id=unbound_agent)
    unbound_session = _request(
        workspace,
        PrincipalClass.AGENT,
        unbound_agent,
        (namespace_ids["SESSION"],),
        (workspace_subject, unbound_subject, session_subject),
    )
    assert await search.authorize(unbound_session) == ()

    denied_attempt = unbound_session.model_copy(update={"attempt_id": uuid4()})
    with pytest.raises(PermanentPortError, match="no requested namespace"):
        await HybridRetriever(
            search, NoopReranker(), PostgresRetrievalAudit(engine, workspace)
        ).retrieve(denied_attempt)
    async with engine.begin() as connection:
        row = (
            (
                await connection.execute(
                    text("SELECT * FROM retrieval_attempts WHERE attempt_id = :attempt_id"),
                    {"attempt_id": denied_attempt.attempt_id},
                )
            )
            .mappings()
            .one()
        )
    assert row["outcome"] == "DENIED"
    assert row["principal_class"] == "AGENT"
    assert row["principal_id"] == unbound_agent
    assert row["requested_namespace_ids"] == [namespace_ids["SESSION"]]
    assert row["searched_namespace_ids"] == []
    assert row["result_chunk_ids"] == []
    assert "query" not in row
    assert "text" not in row

    with pytest.raises(DBAPIError, match="append-only") as mutation:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE retrieval_attempts SET outcome = 'ALLOWED' WHERE attempt_id = :id"),
                {"id": denied_attempt.attempt_id},
            )
    assert getattr(mutation.value.orig, "sqlstate", None) == "27000"

    role = f"agora_t506_{workspace.hex[:12]}"
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        await connection.execute(text(f'GRANT SELECT ON retrieval_attempts TO "{role}"'))
        await connection.execute(text(f'SET LOCAL ROLE "{role}"'))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(workspace)},
        )
        own_count = await connection.scalar(text("SELECT count(*) FROM retrieval_attempts"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(uuid4())},
        )
        other_count = await connection.scalar(text("SELECT count(*) FROM retrieval_attempts"))
    assert own_count == 1
    assert other_count == 0

    await asyncio.to_thread(command.check, config)
    await engine.dispose()
