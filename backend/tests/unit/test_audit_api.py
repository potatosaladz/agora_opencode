"""T14-06 authenticated Audit Search API tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api import create_app
from app.api.audit_contracts import AuditCompleteness, AuditIntegrity, AuditQuestion
from app.api.routes import audit as audit_routes
from app.common.ids import public_id
from app.config import Settings
from app.ports.auth import VerifiedPrincipal, WorkspaceRole
from tests.traceability import req

WS = UUID("018f0000-0000-7000-8000-000000000001")
OTHER_WS = UUID("018f0000-0000-7000-8000-000000000002")
SESSION = UUID("018f0000-0000-7000-8000-000000000003")
USER = UUID("018f0000-0000-7000-8000-000000000004")
NOW = datetime(2026, 9, 14, tzinfo=UTC)


class Sessions:
    async def get(self, workspace_id: UUID, session_id: UUID) -> object | None:
        return object() if (workspace_id, session_id) == (WS, SESSION) else None


class AccessLogs:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    async def record(self, entry: Any) -> None:
        self.entries.append(entry)


@dataclass(slots=True)
class Tx:
    sessions: Sessions
    access_logs: AccessLogs
    artifacts: Any = None
    consensus_results: Any = None
    lifecycle: Any = None
    session_participants: Any = None
    graph: Any = None
    citations: Any = None
    ledger: Any = None
    audit_anchors: Any = None
    dissent_explanations: Any = None


@dataclass(slots=True)
class Verifier:
    principal: VerifiedPrincipal

    async def verify(self, token: str) -> VerifiedPrincipal:
        assert token == "valid"
        return self.principal


class Container:
    def __init__(self, base: Any, principal: VerifiedPrincipal, tx: Tx) -> None:
        self.database = base.database
        self.readiness_checks = base.readiness_checks
        self.access_token_verifier = Verifier(principal)
        self._base = base
        self._tx = tx

    @asynccontextmanager
    async def reasoning_transaction(self, workspace_id: UUID) -> AsyncIterator[Tx]:
        assert workspace_id == self.access_token_verifier.principal.workspace_id
        yield self._tx

    async def close(self) -> None:
        await self._base.close()


def _client(
    role: WorkspaceRole,
    *,
    workspace_id: UUID = WS,
    scopes: frozenset[str] = frozenset({"audit:read"}),
) -> tuple[TestClient, Tx]:
    tx = Tx(Sessions(), AccessLogs())
    principal = VerifiedPrincipal("oidc|auditor", USER, workspace_id, role, scopes)

    async def builder(config: Settings) -> Any:
        from app.composition import build_container

        return Container(await build_container(config), principal, tx)

    app = create_app(
        Settings(environment="test", object_store="inmemory"), container_builder=builder
    )
    return TestClient(app), tx


def _input(question: AuditQuestion) -> dict[str, Any]:
    value: dict[str, Any] = {"question": question.value}
    if question in (AuditQuestion.Q1, AuditQuestion.Q2):
        value["artifact_id"] = public_id("artifact", SESSION)
    if question in (AuditQuestion.Q3, AuditQuestion.Q4, AuditQuestion.Q6):
        value["round"] = 1
    if question is AuditQuestion.Q7:
        value["recommendation_id"] = public_id("recommendation", SESSION)
        value["limit"] = 20
    return value


def _answer_for(question: AuditQuestion) -> dict[str, Any]:
    common: dict[AuditQuestion, dict[str, Any]] = {
        AuditQuestion.Q1: {
            "kind": "ARTIFACT_RATIONALE",
            "artifact_id": public_id("artifact", SESSION),
            "provenance": None,
            "committed_by_event": None,
            "originating_turn_event": None,
        },
        AuditQuestion.Q2: {
            "kind": "ARTIFACT_REVISION_HISTORY",
            "artifact_id": public_id("artifact", SESSION),
            "revisions": (),
        },
        AuditQuestion.Q3: {
            "kind": "ROUND_CONTEXT",
            "round": 1,
            "participants": (),
            "turn_events": (),
        },
        AuditQuestion.Q4: {
            "kind": "DISSENT_SUPPRESSION_CHECK",
            "consensus_result_id": None,
            "outcome": None,
            "all_persisted_positions_included": False,
            "contributions": (),
            "minority_report": (),
        },
        AuditQuestion.Q5: {
            "kind": "SESSION_TERMINATION",
            "final_state": None,
            "final_round": None,
            "ended_at": None,
            "last_event": None,
        },
        AuditQuestion.Q6: {"kind": "STRATEGY_USAGE", "strategy": None},
        AuditQuestion.Q7: {
            "kind": "RECOMMENDATION_ACCESS",
            "recommendation_id": public_id("recommendation", SESSION),
            "recommendation_created_at": NOW.isoformat(),
            "boundary": "STRICTLY_BEFORE_RECOMMENDATION_CREATED_AT",
            "entries": (),
        },
        AuditQuestion.Q8: {
            "kind": "CHAIN_VERIFICATION",
            "event_count": 0,
            "ledger_valid": True,
            "ledger_reason": None,
            "ledger_head_hash": "sha256:" + "0" * 64,
            "chain_valid": None,
            "first_invalid_day": None,
            "anchors": (),
        },
    }
    return common[question]


@req("FR-802", "FR-807", "NFR-006", "NFR-010", "NFR-019")
@pytest.mark.parametrize("question", list(AuditQuestion))
def test_all_eight_queries_are_reachable_logged_and_public(
    monkeypatch: pytest.MonkeyPatch, question: AuditQuestion
) -> None:
    async def answer(*args: Any) -> tuple[Any, ...]:
        del args
        return (
            _answer_for(question),
            ({"order": 1, "source": "persisted"},),
            {
                "completeness": AuditCompleteness.COMPLETE,
                "completeness_reasons": (),
                "integrity": (
                    AuditIntegrity.VERIFIED_UNALTERED
                    if question is AuditQuestion.Q8
                    else AuditIntegrity.NOT_APPLICABLE
                ),
                "integrity_reasons": (),
            },
            {"truncated": False, "next_cursor": None},
        )

    monkeypatch.setattr(audit_routes, "_answer", answer)
    client, tx = _client(WorkspaceRole.VIEWER)
    path = f"/api/v1/sessions/{public_id('session', SESSION)}/audit/query"
    with client:
        response = client.post(
            path, headers={"Authorization": "Bearer valid"}, json=_input(question)
        )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["question"] == question.value
    assert response.json()["data"]["evidence"][0]["order"] == 1
    assert str(WS) not in response.text
    assert str(SESSION) not in response.text
    assert tx.access_logs.entries[-1].scope_ids == ("audit:read", f"audit:{question.value}")


@req("FR-802", "FR-807", "NFR-006", "NFR-010")
@pytest.mark.parametrize("role", list(WorkspaceRole))
def test_audit_query_requires_authentication_and_all_workspace_roles(
    monkeypatch: pytest.MonkeyPatch, role: WorkspaceRole
) -> None:
    async def answer(*args: Any) -> tuple[Any, ...]:
        del args
        return (
            _answer_for(AuditQuestion.Q8),
            (),
            {
                "completeness": AuditCompleteness.INCOMPLETE,
                "completeness_reasons": ("NO_PUBLISHED_ANCHORS",),
                "integrity": AuditIntegrity.NOT_VERIFIABLE,
                "integrity_reasons": ("NO_PUBLISHED_ANCHORS",),
            },
            {"truncated": False, "next_cursor": None},
        )

    monkeypatch.setattr(audit_routes, "_answer", answer)
    client, _ = _client(role)
    path = f"/api/v1/sessions/{public_id('session', SESSION)}/audit/query"
    with client:
        denied = client.post(path, json={"question": "Q8"})
        allowed = client.post(
            path,
            headers={"Authorization": "Bearer valid"},
            json={"question": "Q8"},
        )
    assert denied.status_code == 401
    assert denied.headers["content-type"].startswith("application/problem+json")
    assert allowed.status_code == 200


@req("FR-802", "NFR-010")
def test_audit_query_requires_explicit_audit_read_scope() -> None:
    client, _ = _client(WorkspaceRole.ADMIN, scopes=frozenset())
    with client:
        response = client.post(
            f"/api/v1/sessions/{public_id('session', SESSION)}/audit/query",
            headers={"Authorization": "Bearer valid"},
            json={"question": "Q8"},
        )
    assert response.status_code == 403


@req("FR-802", "NFR-010")
def test_audit_route_declares_role_and_scope_policy() -> None:
    route = next(
        route
        for route in audit_routes.router.routes
        if isinstance(route, APIRoute) and route.path.endswith("/audit/query")
    )
    assert route.endpoint.__agora_workspace_roles__ == frozenset(WorkspaceRole)  # type: ignore[attr-defined]
    assert route.endpoint.__agora_required_scopes__ == frozenset({"audit:read"})  # type: ignore[attr-defined]


@req("FR-802", "NFR-010")
@pytest.mark.parametrize(
    ("session_id", "body", "status"),
    [
        ("ses_bad", {"question": "Q8"}, 404),
        (public_id("session", SESSION), {"question": "Q9"}, 400),
        (public_id("session", SESSION), {"question": "Q1"}, 400),
        (public_id("session", SESSION), {"question": "Q5", "round": 1}, 400),
        (public_id("session", SESSION), {"question": "Q7", "recommendation_id": "rec_bad"}, 400),
    ],
)
def test_audit_query_rejects_malformed_or_wrong_inputs(
    session_id: str, body: dict[str, Any], status: int
) -> None:
    client, _ = _client(WorkspaceRole.VIEWER)
    with client:
        response = client.post(
            f"/api/v1/sessions/{session_id}/audit/query",
            headers={"Authorization": "Bearer valid"},
            json=body,
        )
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")


@req("FR-802", "NFR-010")
def test_audit_query_hides_cross_workspace_session() -> None:
    client, _ = _client(WorkspaceRole.VIEWER, workspace_id=OTHER_WS)
    with client:
        response = client.post(
            f"/api/v1/sessions/{public_id('session', SESSION)}/audit/query",
            headers={"Authorization": "Bearer valid"},
            json={"question": "Q8"},
        )
    assert response.status_code == 404


@req("FR-802", "NFR-010")
def test_q1_preserves_zero_depth_and_maps_bad_cursor_to_problem_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Any] = []

    class Query:
        def __init__(self, *args: Any) -> None:
            del args

        async def artifact_rationale(self, *args: Any, **kwargs: Any) -> None:
            captured.append((args, kwargs))
            raise ValueError("invalid traversal cursor")

    monkeypatch.setattr(audit_routes, "AuditQueryService", Query)
    monkeypatch.setattr(audit_routes, "ProvenanceService", lambda *args: object())
    client, _ = _client(WorkspaceRole.VIEWER)
    with client:
        response = client.post(
            f"/api/v1/sessions/{public_id('session', SESSION)}/audit/query",
            headers={"Authorization": "Bearer valid"},
            json={
                "question": "Q1",
                "artifact_id": public_id("artifact", SESSION),
                "max_depth": 0,
                "cursor": "bad",
            },
        )
    assert response.status_code == 400
    assert captured[0][1]["max_depth"] == 0
    assert response.headers["content-type"].startswith("application/problem+json")
