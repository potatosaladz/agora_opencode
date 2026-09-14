"""End-to-end HTTP to PostgreSQL acceptance for the Phase 3 API boundary."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.api import create_app
from app.common.ids import public_id, uuid7
from app.config import Settings
from app.ports.auth import VerifiedPrincipal, WorkspaceRole
from tests.traceability import req

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _database_url() -> str | None:
    configured = os.getenv("TEST_DATABASE_URL")
    if configured:
        return configured
    host = os.getenv("POSTGRES_HOST")
    password = os.getenv("POSTGRES_PASSWORD")
    if not host or password is None:
        return None
    return (
        f"postgresql+asyncpg://agora:{quote_plus(password)}@"
        f"{host}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'agora')}"
    )


_DATABASE_URL = _database_url()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DATABASE_URL, reason="PostgreSQL test settings are not configured"),
]


@dataclass(slots=True)
class _Verifier:
    principal: VerifiedPrincipal

    async def verify(self, _token: str) -> VerifiedPrincipal:
        return self.principal


async def _reset_database(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


def _upgrade(url: str) -> None:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["database_url_overridden"] = True
    command.upgrade(config, "head")


async def _seed(url: str) -> tuple[VerifiedPrincipal, str]:
    workspace_id, user_id, agent_id, logical_id = uuid7(), uuid7(), uuid7(), uuid7()
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO workspaces (id, slug, name) VALUES (:id, :slug, 'API test')"),
            {"id": workspace_id, "slug": f"api-{workspace_id.hex}"},
        )
        await connection.execute(
            text(
                "INSERT INTO users (id, oidc_issuer, oidc_subject, display_name) "
                "VALUES (:id, 'https://idp.example', :subject, 'API user')"
            ),
            {"id": user_id, "subject": f"api-{user_id.hex}"},
        )
        await connection.execute(
            text(
                "INSERT INTO workspace_members (workspace_id, user_id, role) "
                "VALUES (:workspace_id, :user_id, 'RESEARCHER')"
            ),
            {"workspace_id": workspace_id, "user_id": user_id},
        )
        await connection.execute(
            text(
                "INSERT INTO agent_definitions ("
                "id, workspace_id, logical_id, version, name, domain, role_kind, strategy_ref, "
                "strategy_ver, prompt_ref, prompt_hash, status) VALUES ("
                ":id, :workspace_id, :logical_id, 1, 'API agent', 'testing', 'domain_expert', "
                "'strategies/test', '1', 'prompts/test', 'sha256:test', 'ACTIVE')"
            ),
            {"id": agent_id, "workspace_id": workspace_id, "logical_id": logical_id},
        )
    await engine.dispose()
    return (
        VerifiedPrincipal("oidc|api", user_id, workspace_id, WorkspaceRole.RESEARCHER),
        public_id("agent", agent_id),
    )


async def _counts(url: str, workspace_id: object) -> tuple[int, int, int, int, int]:
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(workspace_id)},
        )
        counts: list[int] = []
        for table in (
            "sessions",
            "reasoning_artifacts",
            "graph_nodes",
            "reasoning_events",
            "api_idempotency_records",
        ):
            counts.append(int(await connection.scalar(text(f"SELECT count(*) FROM {table}"))))
    await engine.dispose()
    return counts[0], counts[1], counts[2], counts[3], counts[4]


def _settings(url: str) -> Settings:
    parsed = make_url(url)
    assert parsed.host
    assert parsed.database
    assert parsed.username
    return Settings(
        environment="test",
        event_bus="inmemory",
        cache="inmemory",
        object_store="inmemory",
        secret_provider="env_file",
        metrics_enabled=False,
        postgres_host=parsed.host,
        postgres_port=parsed.port or 5432,
        postgres_db=parsed.database,
        postgres_user=parsed.username,
        postgres_password=SecretStr(parsed.password or ""),
    )


@req("FR-101", "FR-103")
def test_phase3_http_create_read_and_replay_are_atomic() -> None:
    assert _DATABASE_URL is not None
    asyncio.run(_reset_database(_DATABASE_URL))
    _upgrade(_DATABASE_URL)
    principal, agent_id = asyncio.run(_seed(_DATABASE_URL))
    app = create_app(_settings(_DATABASE_URL))
    objective = {
        "kind": "OBJECTIVE",
        "payload": {
            "name": "Minimize cost",
            "objective_type": "UTILITY",
            "direction": "MINIMIZE",
            "weight": "1",
            "weight_rationale": "Primary objective",
            "time_horizon": "one year",
            "conflicts_with_ids": [],
        },
        "provenance": {"origin": "HUMAN", "reference": "api-test"},
        "source_references": [],
        "parent_relationships": [],
        "metadata": {},
    }
    session_request = {
        "problem_statement": "Choose a cost-effective option",
        "agent_definition_ids": [agent_id],
        "objectives": [objective],
        "constraints": [],
        "budget": {"max_rounds": 4, "max_tokens": 10000, "max_usd": "25"},
    }
    headers = {"Authorization": "Bearer integration", "Idempotency-Key": "create-session"}
    with TestClient(app) as client:
        app.state.container.access_token_verifier = _Verifier(principal)
        created = client.post("/api/v1/sessions", headers=headers, json=session_request)
        replay = client.post("/api/v1/sessions", headers=headers, json=session_request)
        assert created.status_code == replay.status_code == 201, (created.text, replay.text)
        assert replay.json() == created.json()
        assert replay.headers["Idempotency-Replayed"] == "true"

        session_id = created.json()["data"]["id"]
        read_session = client.get(
            f"/api/v1/sessions/{session_id}", headers={"Authorization": "Bearer integration"}
        )
        assert read_session.status_code == 200
        assert read_session.json()["data"]["status"] == "DRAFT"

        claim_request = {
            "kind": "CLAIM",
            "payload": {
                "statement": "The option is affordable",
                "claim_type": "FACTUAL",
                "direction": "SUPPORTS",
                "strength": "WEAK",
                "supporting_evidence_ids": [],
                "opposing_evidence_ids": [],
                "review_status": "PROPOSED",
            },
            "provenance": {"origin": "HUMAN", "reference": "api-test"},
            "source_references": [],
            "parent_relationships": [],
            "metadata": {},
        }
        claim = client.post(
            f"/api/v1/sessions/{session_id}/artifacts",
            headers={**headers, "Idempotency-Key": "create-claim"},
            json=claim_request,
        )
        assert claim.status_code == 201, claim.text
        assert claim.json()["data"]["attributes"]["unsupported"] is True
        artifact_id = claim.json()["data"]["id"]
        read_claim = client.get(
            f"/api/v1/artifacts/{artifact_id}",
            headers={"Authorization": "Bearer integration"},
        )
        assert read_claim.status_code == 200
        assert read_claim.headers["ETag"] == "1"

    assert asyncio.run(_counts(_DATABASE_URL, principal.workspace_id)) == (1, 2, 2, 3, 2)
