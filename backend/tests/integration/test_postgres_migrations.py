"""PostgreSQL acceptance evidence for clean migrations and tenant RLS."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.agent_registry import SqlAlchemyAgentRegistry
from app.db.session import Database
from app.domain.agent_registry import (
    AgentDefinition,
    AgentRoleKind,
    AgentStatus,
    CredentialEnvelope,
    LLMCallRecord,
    LLMConfiguration,
    ProviderKind,
)
from app.ports.errors import PermanentPortError
from app.ports.storage import SecretRef
from tests.traceability import req

_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="TEST_DATABASE_URL is not configured"),
]


@req("FR-109", "NFR-010")
async def test_clean_upgrade_and_cross_tenant_rls() -> None:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(command.upgrade, config, "head")

    workspace_a, workspace_b = uuid4(), uuid4()
    user_a, user_b = uuid4(), uuid4()
    record_a = uuid4()
    async with engine.begin() as connection:
        await connection.execute(text("DROP ROLE IF EXISTS agora_t104_app"))
        await connection.execute(text("CREATE ROLE agora_t104_app NOLOGIN"))
        await connection.execute(text("GRANT USAGE ON SCHEMA public TO agora_t104_app"))
        await connection.execute(text("GRANT SELECT ON workspaces, users TO agora_t104_app"))
        await connection.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_records, workspace_members "
                "TO agora_t104_app"
            )
        )
        await connection.execute(
            text("INSERT INTO workspaces (id, slug, name) VALUES (:a, 'a', 'A'), (:b, 'b', 'B')"),
            {"a": workspace_a, "b": workspace_b},
        )
        await connection.execute(
            text(
                "INSERT INTO users (id, oidc_issuer, oidc_subject, display_name) VALUES "
                "(:a, 'https://idp.example', 'subject-a', 'A'), "
                "(:b, 'https://idp.example', 'subject-b', 'B')"
            ),
            {"a": user_a, "b": user_b},
        )
        assert (
            await connection.scalar(text("SELECT enum_range(NULL::workspace_role)::text"))
            == "{ADMIN,RESEARCHER,OPERATOR,VIEWER}"
        )
        await connection.execute(text("SET ROLE agora_t104_app"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(workspace_a)},
        )
        await connection.execute(
            text("INSERT INTO tenant_records (id, workspace_id, label) VALUES (:id, :ws, 'owned')"),
            {"id": record_a, "ws": workspace_a},
        )
        await connection.execute(
            text(
                "INSERT INTO workspace_members (workspace_id, user_id, role) "
                "VALUES (:workspace_id, :user_id, 'ADMIN')"
            ),
            {"workspace_id": workspace_a, "user_id": user_a},
        )

    async with engine.begin() as connection:
        await connection.execute(text("SET ROLE agora_t104_app"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(workspace_b)},
        )
        assert await connection.scalar(text("SELECT count(*) FROM tenant_records")) == 0
        assert await connection.scalar(text("SELECT count(*) FROM workspace_members")) == 0
        result = await connection.execute(
            text("UPDATE tenant_records SET label = 'cross-tenant' WHERE id = :id"),
            {"id": record_a},
        )
        assert result.rowcount == 0

    async with engine.begin() as connection:
        await connection.execute(text("SET ROLE agora_t104_app"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(workspace_b)},
        )
        with pytest.raises(DBAPIError, match="row-level security policy"):
            await connection.execute(
                text(
                    "INSERT INTO workspace_members (workspace_id, user_id, role) "
                    "VALUES (:workspace_id, :user_id, 'VIEWER')"
                ),
                {"workspace_id": workspace_a, "user_id": user_b},
            )

    async with engine.begin() as connection:
        await connection.execute(text("SET ROLE agora_t104_app"))
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(workspace_b)},
        )
        with pytest.raises(DBAPIError, match="row-level security policy"):
            await connection.execute(
                text(
                    "INSERT INTO tenant_records (id, workspace_id, label) "
                    "VALUES (:id, :workspace_id, 'cross-tenant')"
                ),
                {"id": uuid4(), "workspace_id": workspace_a},
            )

    await asyncio.to_thread(command.check, config)
    await engine.dispose()


@req("FR-201", "FR-202")
async def test_agent_registry_migration_schema_and_repository_round_trip() -> None:
    assert _DATABASE_URL is not None
    engine = create_async_engine(_DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))

    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", _DATABASE_URL.replace("%", "%%"))
    alembic_config.attributes["database_url_overridden"] = True
    await asyncio.to_thread(command.upgrade, alembic_config, "head")

    async with engine.connect() as connection:
        constraints = dict(
            (
                await connection.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) "
                        "FROM pg_constraint "
                        "WHERE conrelid = 'public.llm_credential_envelopes'::regclass"
                    )
                )
            )
            .tuples()
            .all()
        )
        assert constraints["pk_llm_credential_envelopes"] == "PRIMARY KEY (llm_config_id)"
        assert constraints["fk_llm_credential_envelopes_config_workspace"] == (
            "FOREIGN KEY (llm_config_id, workspace_id) "
            "REFERENCES llm_configurations(id, workspace_id) ON DELETE CASCADE"
        )
        algorithm_check = constraints["ck_llm_credential_envelopes_algorithm"]
        assert "algorithm" in algorithm_check
        assert "AES-256-GCM" in algorithm_check

        binary_columns = dict(
            (
                await connection.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name = 'llm_credential_envelopes' "
                        "AND column_name IN "
                        "('ciphertext', 'credential_nonce', 'wrapped_data_key', 'wrapping_nonce')"
                    )
                )
            )
            .tuples()
            .all()
        )
        assert binary_columns == {
            "ciphertext": "bytea",
            "credential_nonce": "bytea",
            "wrapped_data_key": "bytea",
            "wrapping_nonce": "bytea",
        }

        rls_rows = (
            await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN "
                    "('llm_configurations', 'llm_credential_envelopes', "
                    "'agent_definitions', 'llm_call_records')"
                )
            )
        ).tuples()
        assert {name: (enabled, forced) for name, enabled, forced in rls_rows} == {
            "llm_configurations": (True, True),
            "llm_credential_envelopes": (True, True),
            "agent_definitions": (True, True),
            "llm_call_records": (True, True),
        }

    workspace_id = uuid4()
    config_id = uuid4()
    logical_id = uuid4()
    first_id, second_id = uuid4(), uuid4()
    configuration = LLMConfiguration(
        id=config_id,
        workspace_id=workspace_id,
        name="primary-remote",
        provider_kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url="https://provider.example/v1",
        model="reasoning-model",
        embedding_model="embedding-model",
        api_version="2026-09-01",
        secret_ref=SecretRef(provider="swarm_secret", name="provider-key", version=3),
        capabilities={"structured_output": True, "context_tokens": 32768},
        rate_limit={"requests_per_minute": 60},
    )
    envelope = CredentialEnvelope(
        ciphertext=b"\x00encrypted-credential\xff",
        credential_nonce=b"credential-nonce",
        wrapped_data_key=b"\x00wrapped-data-key\xff",
        wrapping_nonce=b"wrapping-nonce",
        master_key_ref=SecretRef(provider="swarm_secret", name="llm-master-key", version=7),
    )
    first = AgentDefinition(
        id=first_id,
        workspace_id=workspace_id,
        logical_id=logical_id,
        version=1,
        name="policy-expert",
        domain="policy",
        role_kind=AgentRoleKind.DOMAIN_EXPERT,
        objectives=("Compare supported alternatives.",),
        constraints=("Cite uncertainty.",),
        knowledge_ns=(uuid4(), uuid4()),
        strategy_ref="strategies/constraint-aware",
        strategy_ver="1.0.0",
        prompt_ref="prompts/policy-expert-v1",
        prompt_hash="sha256:first",
        llm_config_id=config_id,
        tool_perms=("retrieval.search",),
        budget={"max_tokens": 4096, "max_cost_usd": "0.25"},
        status=AgentStatus.ACTIVE,
    )
    second = replace(
        first,
        id=second_id,
        version=2,
        prompt_ref="prompts/policy-expert-v2",
        prompt_hash="sha256:second",
    )
    call_record = LLMCallRecord(
        id=uuid4(),
        workspace_id=workspace_id,
        session_id=uuid4(),
        agent_def_id=second_id,
        llm_config_id=config_id,
        provider="openai_compatible",
        model="reasoning-model",
        input_tokens=101,
        output_tokens=23,
        cost_usd=Decimal("0.00123456"),
        latency_ms=271,
        finish_reason="stop",
        retry_attempts=1,
        raw_artifact_ref="llm-traces/llm/corr-db/trace.json#sha256:abc",
        correlation_id="corr-db",
    )

    database = Database(engine)
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO workspaces (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": workspace_id, "slug": f"registry-{workspace_id.hex}", "name": "Registry"},
        )

    async with database.session(workspace_id) as session:
        registry = SqlAlchemyAgentRegistry(session)
        await registry.add_configuration(configuration)
        await registry.put_credential_envelope(config_id, workspace_id, envelope)
        await registry.add_definition(first)
        await registry.add_definition_version(first.id, second)

    async def record_call() -> None:
        async with database.session(workspace_id) as session:
            await SqlAlchemyAgentRegistry(session).add_call_record(call_record)

    await asyncio.gather(*(record_call() for _ in range(4)))
    await record_call()

    with pytest.raises(PermanentPortError, match="reused with different content"):
        async with database.session(workspace_id) as session:
            await SqlAlchemyAgentRegistry(session).add_call_record(
                replace(call_record, output_tokens=call_record.output_tokens + 1)
            )

    async with database.session(workspace_id) as session:
        registry = SqlAlchemyAgentRegistry(session)
        stored_configuration = await registry.get_configuration(config_id)
        stored_envelope = await registry.get_credential_envelope(config_id)
        stored_first = await registry.get_definition(first_id)
        stored_second = await registry.get_definition(second_id)
        stored_calls = await registry.list_call_records()

    assert stored_configuration is not None
    assert replace(stored_configuration, created_at=None, updated_at=None) == configuration
    assert stored_envelope == envelope
    assert stored_first is not None
    assert replace(stored_first, created_at=None, updated_at=None) == replace(
        first, status=AgentStatus.DEPRECATED, superseded_by=second_id
    )
    assert stored_second is not None
    assert replace(stored_second, created_at=None, updated_at=None) == second
    assert len(stored_calls) == 1
    assert replace(stored_calls[0], created_at=None) == call_record

    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE agent_definitions SET referenced_at = now() WHERE id = :id"),
            {"id": second_id},
        )

    with pytest.raises(DBAPIError, match="referenced agent definitions are immutable"):
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE agent_definitions SET prompt_ref = 'tampered' WHERE id = :id"),
                {"id": second_id},
            )

    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE agent_definitions SET status = 'WITHDRAWN' WHERE id = :id"),
            {"id": second_id},
        )
        assert (
            await connection.scalar(
                text("SELECT status FROM agent_definitions WHERE id = :id"), {"id": second_id}
            )
            == "WITHDRAWN"
        )

    await asyncio.to_thread(command.check, alembic_config)
    await database.close()
