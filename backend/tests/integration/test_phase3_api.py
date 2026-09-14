"""End-to-end HTTP to PostgreSQL acceptance for the Phase 3 API boundary."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.api import create_app
from app.common.ids import parse_id, public_id, uuid7
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


async def _graph_nodes(url: str, workspace_id: object) -> list[UUID]:
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(workspace_id)},
        )
        rows = (await connection.execute(text("SELECT id FROM graph_nodes ORDER BY id"))).scalars()
        values = list(rows)
    await engine.dispose()
    return values


async def _seed_dissent(
    url: str,
    principal: VerifiedPrincipal,
    session_id: UUID,
    selected_id: UUID,
    warrant_id: UUID,
) -> UUID:
    consensus_id = uuid7()
    explanation: dict[str, object] = {
        "consensus_id": str(consensus_id),
        "outcome": "PARTIAL_CONSENSUS",
        "strategy": "constraint_aware",
        "strategy_version": "1",
        "formula": "persisted integration fixture",
        "weights": {},
        "thresholds": {},
        "contributions": [],
        "derivation": [],
        "caveats": ["support is not probability"],
        "minority_report": [
            {
                "agent_id": str(principal.user_id),
                "position": "OPPOSE",
                "warrant_artifact_ids": [str(warrant_id)],
                "disputed_propositions": [],
                "unresolved_critiques": [],
                "what_would_change": "independent corroboration",
            }
        ],
        "counterfactuals": [],
        "flip_distance": None,
        "degenerate_input": False,
        "input_hash": "sha256:" + "d" * 64,
    }
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(
            text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
            {"workspace_id": str(principal.workspace_id)},
        )
        await connection.execute(
            text(
                "INSERT INTO consensus_results (id, workspace_id, session_id, round, strategy, "
                "strategy_version, outcome, selected_alternative_id, pareto_set, "
                "constraint_report, "
                "conditions, input_hash, created_at) VALUES (:id, :workspace, :session, 1, "
                "'constraint_aware', '1', 'PARTIAL_CONSENSUS', :selected, '{}', '{}'::jsonb, "
                "'[]'::jsonb, :hash, now())"
            ),
            {
                "id": consensus_id,
                "workspace": principal.workspace_id,
                "session": session_id,
                "selected": selected_id,
                "hash": "sha256:" + "d" * 64,
            },
        )
        await connection.execute(
            text(
                "INSERT INTO consensus_explanations (id, workspace_id, consensus_id, explanation, "
                "created_at) VALUES (:id, :workspace, :consensus, "
                "CAST(:explanation AS jsonb), now())"
            ),
            {
                "id": consensus_id,
                "workspace": principal.workspace_id,
                "consensus": consensus_id,
                "explanation": json.dumps(explanation),
            },
        )
    await engine.dispose()
    return consensus_id


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


@req(
    "FR-101",
    "FR-103",
    "FR-505",
    "FR-609",
    "FR-805",
    "NFR-004",
    "NFR-005",
    "NFR-010",
    "NFR-019",
)
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
        dissent = client.get(
            f"/api/v1/sessions/{session_id}/dissent",
            headers={"Authorization": "Bearer integration"},
        )
        assert dissent.status_code == 200, dissent.text
        assert dissent.json()["data"] == {
            "session_id": session_id,
            "evaluated": False,
            "empty_reason": "NO_CONSENSUS_RESULT",
            "majority": None,
            "evidence_context": {
                "supports_selected": [],
                "opposes_selected": [],
                "qualifies_selected": [],
            },
            "minority": [],
            "critiques": [],
        }
        register = client.get(
            f"/api/v1/sessions/{session_id}/assumptions",
            headers={"Authorization": "Bearer integration"},
        )
        assert register.status_code == 200, register.text
        assert register.json()["data"] == {"session_id": session_id, "items": []}
        hidden = client.get(
            f"/api/v1/sessions/{public_id('session', uuid7())}/assumptions",
            headers={"Authorization": "Bearer integration"},
        )
        assert hidden.status_code == 404

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

        assumption = client.post(
            f"/api/v1/sessions/{session_id}/artifacts",
            headers={**headers, "Idempotency-Key": "create-assumption"},
            json={
                "kind": "ASSUMPTION",
                "payload": {
                    "statement": "Demand remains above the planning floor",
                    "basis": "Observed weekday counts",
                    "materiality": "Changes the selected capacity",
                    "challengeable": True,
                },
                "provenance": {"origin": "HUMAN", "reference": "api-test"},
                "source_references": [],
                "parent_relationships": [],
                "metadata": {},
            },
        )
        assert assumption.status_code == 201, assumption.text
        persisted_register = client.get(
            f"/api/v1/sessions/{session_id}/assumptions",
            headers={"Authorization": "Bearer integration"},
        )
        assert persisted_register.status_code == 200, persisted_register.text
        register_item = persisted_register.json()["data"]["items"][0]
        assert register_item["id"] == assumption.json()["data"]["id"]
        assert register_item["kind"] == "ASSUMPTION"
        assert register_item["statement"] == "Demand remains above the planning floor"
        assert register_item["lifecycle"] == "ACTIVE"
        assert register_item["graph_node_id"].startswith("gnd_")
        assert register_item["symbolic"] is None

        internal_session_id = parse_id("session", session_id)
        internal_artifact_id = parse_id("artifact", artifact_id)
        asyncio.run(
            _seed_dissent(
                _DATABASE_URL,
                principal,
                internal_session_id,
                internal_artifact_id,
                internal_artifact_id,
            )
        )
        persisted_dissent = client.get(
            f"/api/v1/sessions/{session_id}/dissent",
            headers={"Authorization": "Bearer integration"},
        )
        assert persisted_dissent.status_code == 200, persisted_dissent.text
        assert persisted_dissent.json()["data"]["minority"][0]["position"] == "OPPOSE"
        assert persisted_dissent.json()["data"]["minority"][0]["warrants"][0]["id"] == artifact_id
        assert (
            persisted_dissent.json()["data"]["majority"]["selected_alternative_id"] == artifact_id
        )

        graph_nodes = asyncio.run(_graph_nodes(_DATABASE_URL, principal.workspace_id))
        assert len(graph_nodes) == 3
        graph = client.post(
            "/api/v1/graph/subgraph",
            headers={"Authorization": "Bearer integration"},
            json={
                "session_id": session_id,
                "root_ids": [public_id("graph_node", graph_nodes[0])],
                "max_depth": 1,
                "page_size": 1,
            },
        )
        assert graph.status_code == 200, graph.text
        assert graph.json()["data"]["nodes"][0]["id"] == public_id("graph_node", graph_nodes[0])
        assert graph.json()["data"]["next_cursor"] is None

    assert asyncio.run(_counts(_DATABASE_URL, principal.workspace_id)) == (1, 3, 3, 4, 3)
