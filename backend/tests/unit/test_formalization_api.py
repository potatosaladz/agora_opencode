"""Public HTTP contract tests for the T11-01 formalization lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import create_app
from app.common.ids import public_id
from app.config import Settings
from app.domain.phase3_api import IdempotencyRecord
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    Bearing,
    ClaimPayload,
    ClaimType,
    LifecycleStatus,
    Provenance,
    ProvenanceOrigin,
    ReviewStatus,
    Strength,
    artifact_content_hash,
    validate_artifact,
)
from app.ports.auth import VerifiedPrincipal, WorkspaceRole
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{index:012d}") for index in range(1, 20))
NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def source() -> Any:
    values = {
        "id": U[3],
        "workspace_id": U[1],
        "session_id": U[2],
        "logical_id": U[4],
        "kind": ArtifactKind.CLAIM,
        "schema_version": 1,
        "version": 2,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": U[15],
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": U[6],
        "round": 0,
        "payload": ClaimPayload(
            statement="Cost must not exceed 100 USD",
            claim_type=ClaimType.FACTUAL,
            direction=Bearing.SUPPORTS,
            strength=Strength.STRONG,
            supporting_evidence_ids=(),
            opposing_evidence_ids=(),
            review_status=ReviewStatus.ACCEPTED,
        ),
        "provenance": Provenance(origin=ProvenanceOrigin.HUMAN, reference="policy"),
        "source_references": (),
        "parent_relationships": (),
        "confidence": None,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    return validate_artifact({**values, "content_hash": artifact_content_hash(values)})


class Artifacts:
    async def get(
        self, workspace_id: UUID, artifact_id: UUID, *, session_id: UUID | None = None
    ) -> Any:
        item = source()
        return item if workspace_id == item.workspace_id and artifact_id == item.id else None


class Formalizations:
    def __init__(self) -> None:
        self.revisions: list[Any] = []
        self.validations: dict[UUID, Any] = {}
        self.decisions: dict[UUID, Any] = {}

    async def add_revision(self, value: Any) -> None:
        self.revisions.append(value)

    async def head(self, workspace_id: UUID, logical_id: UUID, *, for_update: bool = False) -> Any:
        values = [item for item in self.revisions if item.logical_id == logical_id]
        return max(values, key=lambda item: item.revision) if values else None

    async def revision(
        self, workspace_id: UUID, logical_id: UUID, revision: int | None = None
    ) -> Any:
        values = [
            item
            for item in self.revisions
            if item.logical_id == logical_id and (revision is None or item.revision == revision)
        ]
        return max(values, key=lambda item: item.revision) if values else None

    async def validation(self, workspace_id: UUID, revision_id: UUID) -> Any:
        return self.validations.get(revision_id)

    async def decision(self, workspace_id: UUID, revision_id: UUID) -> Any:
        return self.decisions.get(revision_id)

    async def add_validation(self, value: Any) -> None:
        self.validations[value.formalization_revision_id] = value

    async def add_decision(self, value: Any) -> None:
        self.decisions[value.formalization_revision_id] = value

    async def verify_artifacts(self, value: Any) -> None:
        return None

    async def add_event(self, **values: Any) -> None:
        return None


class Idempotency:
    def __init__(self) -> None:
        self.values: dict[tuple[UUID, str, str], IdempotencyRecord] = {}

    async def load_after_lock(self, workspace_id: UUID, operation: str, key: str) -> Any:
        return self.values.get((workspace_id, operation, key))

    async def save(
        self, workspace_id: UUID, operation: str, key: str, record: IdempotencyRecord
    ) -> None:
        self.values[(workspace_id, operation, key)] = record


class Verifier:
    def __init__(self, principal: VerifiedPrincipal) -> None:
        self.principal = principal

    async def verify(self, token: str) -> VerifiedPrincipal:
        return self.principal


@dataclass
class Tx:
    formalizations: Formalizations
    idempotency: Idempotency
    artifacts: Artifacts


class Container:
    def __init__(self, base: Any, principal: VerifiedPrincipal, tx: Tx) -> None:
        self.database, self.readiness_checks = base.database, base.readiness_checks
        self.access_token_verifier, self._base, self.tx = Verifier(principal), base, tx

    @asynccontextmanager
    async def reasoning_transaction(self, workspace_id: UUID) -> AsyncIterator[Tx]:
        yield self.tx

    async def close(self) -> None:
        await self._base.close()


def client_for(role: WorkspaceRole = WorkspaceRole.RESEARCHER) -> tuple[TestClient, Tx, FastAPI]:
    tx = Tx(Formalizations(), Idempotency(), Artifacts())
    principal = VerifiedPrincipal("oidc|user", U[6], U[1], role)

    async def builder(config: Settings) -> Any:
        from app.composition import build_container

        return Container(await build_container(config), principal, tx)

    app = create_app(
        Settings(environment="test", object_store="inmemory"), container_builder=builder
    )
    return TestClient(app), tx, app


def body() -> dict[str, Any]:
    return {
        "source_artifact_id": public_id("artifact", U[3]),
        "ast": {
            "kind": "operation",
            "operator": "LE",
            "arguments": [{"kind": "symbol", "name": "cost"}, {"kind": "integer", "value": "100"}],
        },
        "symbols": [
            {"name": "cost", "sort": "INTEGER", "meaning": "programme cost", "unit": "USD"}
        ],
        "canonical_rendering": "(cost <= 100)",
        "premise_artifact_ids": [],
        "limitations": ["Nominal USD only"],
        "fidelity_notes": "Timing omitted",
    }


@req("FR-707")
def test_create_read_validate_confirm_and_replay_expose_authoritative_status() -> None:
    client, tx, _ = client_for()
    headers = {"Authorization": "Bearer valid", "Idempotency-Key": "create"}
    with client:
        created = client.post("/api/v1/formalizations", headers=headers, json=body())
        replay = client.post("/api/v1/formalizations", headers=headers, json=body())
        assert created.status_code == 201, created.text
        identity = created.json()["data"]["id"]
        loaded = client.get(
            f"/api/v1/formalizations/{identity}", headers={"Authorization": "Bearer valid"}
        )
        validated = client.post(
            f"/api/v1/formalizations/{identity}/validations",
            headers={**headers, "Idempotency-Key": "validate", "If-Match": "1"},
            json={},
        )
        confirmed = client.post(
            f"/api/v1/formalizations/{identity}/confirmations",
            headers={**headers, "Idempotency-Key": "confirm", "If-Match": "1"},
            json={"reason": "Reviewed against source"},
        )
        revised = client.post(
            f"/api/v1/formalizations/{identity}/revisions",
            headers={**headers, "Idempotency-Key": "revise", "If-Match": "1"},
            json={**body(), "fidelity_notes": "Timing and inflation omitted"},
        )
        historical = client.get(
            f"/api/v1/formalizations/{identity}?revision=1",
            headers={"Authorization": "Bearer valid"},
        )
    assert created.status_code == 201
    assert identity.startswith("frm_")
    assert created.headers["etag"] == "1"
    assert replay.headers["idempotency-replayed"] == "true"
    assert loaded.json()["data"]["validation_status"] == "CANDIDATE"
    assert validated.json()["data"]["validation_status"] == "CANDIDATE"
    assert confirmed.json()["data"]["validation_status"] == "VALIDATED"
    assert confirmed.json()["data"]["enforceable"] is True
    assert revised.status_code == 201
    assert revised.headers["etag"] == "2"
    assert revised.json()["data"]["validation_status"] == "CANDIDATE"
    assert revised.json()["data"]["validation"] is None
    assert historical.json()["data"]["validation_status"] == "VALIDATED"
    assert len(tx.formalizations.revisions) == 2


@req("FR-707")
def test_stale_if_match_changed_replay_and_rbac_fail_closed() -> None:
    client, _, _ = client_for()
    headers = {"Authorization": "Bearer valid", "Idempotency-Key": "create"}
    with client:
        created = client.post("/api/v1/formalizations", headers=headers, json=body())
        assert created.status_code == 201, created.text
        identity = created.json()["data"]["id"]
        stale = client.post(
            f"/api/v1/formalizations/{identity}/validations",
            headers={**headers, "Idempotency-Key": "stale", "If-Match": "2"},
            json={},
        )
        changed = client.post(
            "/api/v1/formalizations",
            headers=headers,
            json={**body(), "fidelity_notes": "different"},
        )
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"
    assert changed.status_code == 409
    viewer, _, _ = client_for(WorkspaceRole.VIEWER)
    with viewer:
        denied = viewer.post("/api/v1/formalizations", headers=headers, json=body())
    assert denied.status_code == 403
