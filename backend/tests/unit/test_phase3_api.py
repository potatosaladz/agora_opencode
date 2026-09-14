"""Contract tests for the tenant-scoped Phase 3 HTTP boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import create_app
from app.api.phase3_contracts import (
    ArtifactCreate,
    ArtifactRevisionCreate,
    SessionCreate,
    artifact_response,
    decode_artifact_payload,
)
from app.api.routes.phase3 import router as phase3_router
from app.common.ids import parse_id, public_id
from app.config import Settings
from app.domain.assumption_register import AssumptionRegisterSnapshot
from app.domain.consensus import (
    ConsensusExplanation,
    ConsensusOutcome,
    ConsensusRunRecord,
    MinorityEntry,
)
from app.domain.critique_handoff import (
    CritiqueExplanationEntry,
    CritiqueExplanationHandoff,
    CritiqueHandoffEmptyReason,
)
from app.domain.explanation import DecisionExplanationSnapshot, PersistedRecommendation
from app.domain.phase3_api import IdempotencyRecord
from app.domain.reasoning import (
    ActorClass,
    AlternativePayload,
    ArtifactKind,
    Bearing,
    ClaimPayload,
    ClaimType,
    CritiqueType,
    GraphEdgeType,
    LifecycleStatus,
    Provenance,
    ProvenanceOrigin,
    Resolution,
    ReviewStatus,
    Severity,
    Strength,
    artifact_content_hash,
    content_hash,
    validate_artifact,
)
from app.domain.reasoning_graph import GraphEdge, GraphNode, TraversalResult
from app.ports.auth import VerifiedPrincipal, WorkspaceRole
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 10))
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


@req("FR-305")
def test_decode_artifact_payload_uses_strict_json_domain_contract() -> None:
    decoded = decode_artifact_payload(
        ArtifactKind.CLAIM,
        {
            "statement": "Affordable",
            "claim_type": "FACTUAL",
            "direction": "SUPPORTS",
            "strength": "WEAK",
            "supporting_evidence_ids": [],
            "opposing_evidence_ids": [],
            "review_status": "PROPOSED",
        },
    )
    assert isinstance(decoded, ClaimPayload)
    assert decoded.claim_type is ClaimType.FACTUAL
    assert decoded.supporting_evidence_ids == ()


@req("FR-305")
def test_decode_artifact_payload_keeps_opaque_json_strings_untouched() -> None:
    decoded = decode_artifact_payload(
        ArtifactKind.UNCERTAINTY,
        {
            "target_id": public_id("artifact", U[0]),
            "uncertainty_type": "MODEL",
            "drivers": [],
            "representation": "DISTRIBUTION",
            "family": "custom",
            "parameters": {"label": "art_not-a-public-id"},
            "unit": "usd",
        },
    )
    assert decoded.parameters["label"] == "art_not-a-public-id"


@req("FR-305")
def test_decode_artifact_payload_reports_malformed_public_ids_as_validation() -> None:
    with pytest.raises(ValidationError):
        decode_artifact_payload(
            ArtifactKind.CLAIM,
            {
                "statement": "Affordable",
                "claim_type": "FACTUAL",
                "direction": "SUPPORTS",
                "strength": "WEAK",
                "supporting_evidence_ids": ["art_invalid"],
                "opposing_evidence_ids": [],
                "review_status": "PROPOSED",
            },
        )


@req("FR-305")
def test_request_contracts_decode_rfc3339_timestamps_through_strict_json() -> None:
    artifact = ArtifactCreate.model_validate(
        {
            "kind": "EVIDENCE",
            "payload": {},
            "provenance": {"origin": "HUMAN", "reference": "test"},
            "source_references": [
                {
                    "reference": "source",
                    "locator": {"page": 1},
                    "content_hash": "sha256:" + "a" * 64,
                    "retrieved_at": "2026-09-05T12:00:00Z",
                }
            ],
            "parent_relationships": [],
            "metadata": {},
        }
    )
    assert artifact.source_references[0].retrieved_at == NOW

    session = SessionCreate.model_validate(
        {
            "problem_statement": "Choose",
            "agent_definition_ids": [public_id("agent", U[0])],
            "objectives": [
                {
                    "kind": "OBJECTIVE",
                    "payload": {},
                    "provenance": {"origin": "HUMAN", "reference": "test"},
                    "source_references": [],
                    "parent_relationships": [],
                    "metadata": {},
                }
            ],
            "constraints": [],
            "budget": {
                "max_rounds": 1,
                "max_tokens": 1,
                "max_usd": "1",
                "deadline_at": "2026-09-05T12:00:00Z",
            },
        }
    )
    assert session.budget.deadline_at == NOW


def settings() -> Settings:
    return Settings(
        environment="test",
        event_bus="inmemory",
        cache="inmemory",
        object_store="inmemory",
        secret_provider="env_file",
    )


@dataclass(slots=True)
class Verifier:
    principal: VerifiedPrincipal

    async def verify(self, token: str) -> VerifiedPrincipal:
        assert token == "valid"
        return self.principal


class Idempotency:
    def __init__(self) -> None:
        self.values: dict[tuple[UUID, str, str], IdempotencyRecord] = {}

    async def load_after_lock(
        self, workspace_id: UUID, operation: str, key: str
    ) -> IdempotencyRecord | None:
        return self.values.get((workspace_id, operation, key))

    async def save(
        self, workspace_id: UUID, operation: str, key: str, record: IdempotencyRecord
    ) -> None:
        self.values[(workspace_id, operation, key)] = record


class Artifacts:
    def __init__(self, artifact: Any = None) -> None:
        self.artifact = artifact

    async def get(
        self, workspace_id: UUID, artifact_id: UUID, *, session_id: UUID | None = None
    ) -> Any:
        if (
            self.artifact
            and self.artifact.id == artifact_id
            and self.artifact.workspace_id == workspace_id
        ):
            return self.artifact
        return None

    async def get_for_update(self, workspace_id: UUID, session_id: UUID, artifact_id: UUID) -> Any:
        return await self.get(workspace_id, artifact_id, session_id=session_id)


@dataclass(slots=True)
class Tx:
    artifacts: Any
    idempotency: Any
    sessions: Any = None
    graph: Any = None
    ledger: Any = None
    citations: Any = None
    consensus_results: Any = None
    critique_handoffs: Any = None
    dissent_explanations: Any = None
    assumption_register: Any = None
    decision_explanations: Any = None


class _TestContainer:
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


def claim() -> Any:
    data: dict[str, Any] = {
        "id": U[0],
        "workspace_id": U[1],
        "session_id": U[2],
        "logical_id": U[3],
        "kind": ArtifactKind.CLAIM,
        "schema_version": 1,
        "version": 1,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": None,
        "owner_actor_class": ActorClass.HUMAN,
        "owner_actor_id": U[4],
        "round": 0,
        "payload": ClaimPayload(
            statement="Unsupported",
            claim_type=ClaimType.FACTUAL,
            direction=Bearing.SUPPORTS,
            strength=Strength.WEAK,
            supporting_evidence_ids=(),
            opposing_evidence_ids=(),
            review_status=ReviewStatus.PROPOSED,
        ),
        "provenance": Provenance(origin=ProvenanceOrigin.HUMAN, reference="test"),
        "source_references": (),
        "parent_relationships": (),
        "confidence": None,
        "metadata": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    data["content_hash"] = artifact_content_hash(data)
    return validate_artifact(data)


@req("FR-305")
def test_public_ids_are_strict_and_round_trip() -> None:
    encoded = public_id("artifact", U[0])
    assert parse_id("artifact", encoded) == U[0]
    for invalid in (
        str(U[0]),
        f"ses_{U[0].hex}",
        f"art_{U[0].hex.upper()}",
        "art_00000000000040008000000000000000",
    ):
        try:
            parse_id("artifact", invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid public id accepted")


@req("FR-305")
def test_claim_response_explicitly_marks_absent_evidence_as_unsupported() -> None:
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.VIEWER)
    response = artifact_response(claim(), principal, request_id="req_test")
    assert response["data"]["attributes"]["unsupported"] is True
    assert response["meta"]["permissions"] == ["artifacts:read"]


@req("FR-305")
def test_artifact_read_is_tenant_scoped_and_write_headers_are_required() -> None:
    artifact = claim()
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.VIEWER)
    tx = Tx(Artifacts(artifact), Idempotency())

    async def builder(config: Settings) -> Any:
        from app.composition import build_container

        return _TestContainer(await build_container(config), principal, tx)

    app = create_app(settings(), container_builder=builder)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer valid"}
        response = client.get(
            f"/api/v1/artifacts/{public_id('artifact', artifact.id)}", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["unsupported"] is True
        missing = client.post(
            f"/api/v1/sessions/{public_id('session', U[2])}/artifacts", headers=headers, json={}
        )
        assert missing.status_code == 403


class ProvenanceGraph:
    def __init__(self, artifact: Any, *, truncated: bool = False) -> None:
        self.node = GraphNode(
            id=U[5],
            workspace_id=artifact.workspace_id,
            session_id=artifact.session_id,
            kind=artifact.kind,
            ref_id=artifact.id,
            label="Claim",
        )
        self.truncated = truncated

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        if (
            workspace_id == self.node.workspace_id
            and session_id == self.node.session_id
            and artifact_id == self.node.ref_id
        ):
            return self.node
        return None

    async def trace_backward(self, *args: Any, **kwargs: Any) -> TraversalResult:
        del args, kwargs
        return TraversalResult(nodes=(self.node,), truncated=self.truncated)


class ProvenanceCitations:
    async def citations_for_evidence(self, *args: Any) -> tuple[()]:
        del args
        return ()


class Subgraph:
    def __init__(self, artifact: Any) -> None:
        self.root = GraphNode(
            id=U[5],
            workspace_id=artifact.workspace_id,
            session_id=artifact.session_id,
            kind=artifact.kind,
            ref_id=artifact.id,
            label="Root claim",
        )
        self.other = GraphNode(
            id=U[6],
            workspace_id=artifact.workspace_id,
            session_id=artifact.session_id,
            kind=ArtifactKind.EVIDENCE,
            ref_id=U[7],
            label="Evidence",
        )
        self.edge = GraphEdge(
            id=U[8],
            workspace_id=artifact.workspace_id,
            session_id=artifact.session_id,
            from_node=self.other.id,
            to_node=self.root.id,
            edge_type=GraphEdgeType.SUPPORTS,
            actor_class=ActorClass.HUMAN,
            actor_id=U[4],
        )
        self.calls: list[dict[str, Any]] = []

    async def subgraph(
        self,
        workspace_id: UUID,
        session_id: UUID,
        root_ids: tuple[UUID, ...],
        **kwargs: Any,
    ) -> TraversalResult:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "root_ids": root_ids,
                **kwargs,
            }
        )
        if (
            workspace_id != self.root.workspace_id
            or session_id != self.root.session_id
            or root_ids != (self.root.id,)
        ):
            return TraversalResult()
        if kwargs.get("max_depth") == 0:
            return TraversalResult(nodes=(self.root,))
        if kwargs.get("cursor") == "wrong-query":
            raise ValueError("invalid traversal cursor")
        return TraversalResult(
            nodes=(self.root, self.other),
            edges=(self.edge,),
            truncated=True,
            next_cursor="next-page",
        )


@req("FR-305")
def test_artifact_provenance_route_returns_shape_truncation_and_hidden_404() -> None:
    artifact = claim()
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.VIEWER)
    graph = ProvenanceGraph(artifact, truncated=True)
    tx = Tx(
        Artifacts(artifact),
        Idempotency(),
        graph=graph,
        citations=ProvenanceCitations(),
    )
    client, _ = _client_for(principal, tx)
    path = f"/api/v1/artifacts/{public_id('artifact', artifact.id)}/provenance"
    with client:
        response = client.get(path, headers={"Authorization": "Bearer valid"})
        missing = client.get(
            f"/api/v1/artifacts/{public_id('artifact', U[8])}/provenance",
            headers={"Authorization": "Bearer valid"},
        )
    assert response.status_code == 200
    assert response.json()["data"]["root_artifact_id"] == public_id("artifact", artifact.id)
    assert response.json()["data"]["nodes"][0]["graph_node"]["ref_id"] == public_id(
        "artifact", artifact.id
    )
    assert response.json()["data"]["truncated"] is True
    assert response.json()["data"]["max_depth"] == 12
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")


@req("FR-305")
def test_phase3_routes_declare_frozen_role_matrix() -> None:
    policies = {
        route.path: getattr(route.endpoint, "__agora_workspace_roles__", None)
        for route in phase3_router.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
    }
    assert policies["/api/v1/sessions/{session_id}"] == frozenset(WorkspaceRole)
    assert policies["/api/v1/sessions/{session_id}/dissent"] == frozenset(WorkspaceRole)
    assert policies["/api/v1/sessions/{session_id}/explanation"] == frozenset(WorkspaceRole)
    assert policies["/api/v1/artifacts/{artifact_id}"] == frozenset(WorkspaceRole)
    assert policies["/api/v1/artifacts/{artifact_id}/provenance"] == frozenset(WorkspaceRole)
    assert policies["/api/v1/impact-reports/{report_id}"] == frozenset(WorkspaceRole)
    assert policies["/api/v1/sources/{source_id}/retractions"] == frozenset(
        {WorkspaceRole.ADMIN, WorkspaceRole.RESEARCHER}
    )
    assert policies["/api/v1/sessions"] == frozenset(
        {WorkspaceRole.ADMIN, WorkspaceRole.RESEARCHER}
    )
    assert policies["/api/v1/sessions/{session_id}/start"] == frozenset(
        {WorkspaceRole.ADMIN, WorkspaceRole.RESEARCHER}
    )


@req("FR-805", "NFR-004", "NFR-010", "NFR-019")
@pytest.mark.parametrize("role", list(WorkspaceRole))
def test_graph_subgraph_is_authenticated_and_available_to_every_workspace_role(
    role: WorkspaceRole,
) -> None:
    artifact = claim()
    graph = Subgraph(artifact)
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], role)
    client, _ = _client_for(principal, Tx(Artifacts(artifact), Idempotency(), graph=graph))
    body = {
        "session_id": public_id("session", artifact.session_id),
        "root_ids": [public_id("graph_node", graph.root.id)],
        "max_depth": 2,
        "edge_types": ["SUPPORTS"],
        "page_size": 2,
    }
    with client:
        denied = client.post("/api/v1/graph/subgraph", json=body)
        response = client.post(
            "/api/v1/graph/subgraph",
            headers={"Authorization": "Bearer valid"},
            json=body,
        )
    assert denied.status_code == 401
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [node["id"] for node in data["nodes"]] == [
        public_id("graph_node", graph.root.id),
        public_id("graph_node", graph.other.id),
    ]
    assert data["edges"][0]["id"] == public_id("graph_edge", graph.edge.id)
    assert data["edges"][0]["from_node"] == public_id("graph_node", graph.other.id)
    assert data["edges"][0]["actor_id"] == public_id("user", U[4])
    assert data["truncated"] is True
    assert data["next_cursor"] == "next-page"
    assert graph.calls[-1]["edge_types"] == frozenset({GraphEdgeType.SUPPORTS})


@req("FR-805", "NFR-004", "NFR-010")
@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"session_id": "ses_bad"}, 400),
        ({"root_ids": ["gnd_bad"]}, 400),
        ({"root_ids": []}, 400),
        ({"max_depth": -1}, 400),
        ({"max_depth": 6}, 400),
        ({"page_size": 0}, 400),
        ({"page_size": 201}, 400),
        ({"edge_types": ["NOT_AN_EDGE"]}, 400),
        ({"cursor": "wrong-query"}, 400),
        ({"session_id": public_id("session", U[3])}, 404),
        ({"root_ids": [public_id("graph_node", U[7])]}, 404),
    ],
)
def test_graph_subgraph_rejects_invalid_or_hidden_query(
    change: dict[str, Any], status: int
) -> None:
    artifact = claim()
    graph = Subgraph(artifact)
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.VIEWER)
    client, _ = _client_for(principal, Tx(Artifacts(artifact), Idempotency(), graph=graph))
    body = {
        "session_id": public_id("session", artifact.session_id),
        "root_ids": [public_id("graph_node", graph.root.id)],
        "max_depth": 2,
        "page_size": 100,
        **change,
    }
    with client:
        response = client.post(
            "/api/v1/graph/subgraph",
            headers={"Authorization": "Bearer valid"},
            json=body,
        )
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")


def _revision_body(statement: str = "Replacement") -> dict[str, Any]:
    return {
        "payload": {
            "statement": statement,
            "claim_type": "FACTUAL",
            "direction": "SUPPORTS",
            "strength": "WEAK",
            "supporting_evidence_ids": [],
            "opposing_evidence_ids": [],
            "review_status": "PROPOSED",
        },
        "provenance": {"origin": "HUMAN", "reference": "test"},
        "source_references": [],
        "parent_relationships": [],
        "metadata": {},
        "reason": "Correct wording",
    }


def _client_for(principal: VerifiedPrincipal, tx: Tx) -> tuple[TestClient, FastAPI]:
    async def builder(config: Settings) -> Any:
        from app.composition import build_container

        return _TestContainer(await build_container(config), principal, tx)

    app = create_app(settings(), container_builder=builder)
    return TestClient(app), app


class DissentSessions:
    def __init__(self, visible: bool = True) -> None:
        self.visible = visible

    async def get(self, workspace_id: UUID, session_id: UUID) -> object | None:
        del workspace_id, session_id
        return object() if self.visible else None


class EmptyAssumptionRegister:
    async def read(self, workspace_id: UUID, session_id: UUID) -> AssumptionRegisterSnapshot:
        return AssumptionRegisterSnapshot((), (), (), ())


class DissentConsensus:
    def __init__(
        self,
        results: tuple[ConsensusRunRecord, ...],
        explanations: dict[UUID, ConsensusExplanation],
    ) -> None:
        self.results = results
        self.explanations = explanations

    async def list_results(
        self, workspace_id: UUID, session_id: UUID
    ) -> tuple[ConsensusRunRecord, ...]:
        del workspace_id, session_id
        return self.results

    async def get_explanation(
        self, workspace_id: UUID, result_id: UUID
    ) -> ConsensusExplanation | None:
        del workspace_id
        return self.explanations.get(result_id)

    async def get(self, workspace_id: UUID, result_id: UUID) -> ConsensusExplanation | None:
        return await self.get_explanation(workspace_id, result_id)


@dataclass(slots=True)
class ExplanationReader:
    snapshot: DecisionExplanationSnapshot

    async def read(self, workspace_id: UUID, session_id: UUID) -> DecisionExplanationSnapshot:
        assert workspace_id == U[1]
        assert session_id == U[2]
        return self.snapshot


@dataclass(slots=True)
class DissentHandoffs:
    handoff: CritiqueExplanationHandoff

    async def read(self, workspace_id: UUID, session_id: UUID) -> CritiqueExplanationHandoff:
        assert workspace_id == self.handoff.workspace_id
        assert session_id == self.handoff.session_id
        return self.handoff


class DissentArtifacts:
    def __init__(self, values: tuple[Any, ...] = ()) -> None:
        self.values = {value.id: value for value in values}

    async def get(
        self, workspace_id: UUID, artifact_id: UUID, *, session_id: UUID | None = None
    ) -> Any:
        value = self.values.get(artifact_id)
        if value is None or value.workspace_id != workspace_id or value.session_id != session_id:
            return None
        return value

    async def list_for_session(self, workspace_id: UUID, session_id: UUID) -> tuple[Any, ...]:
        return tuple(
            value
            for value in self.values.values()
            if value.workspace_id == workspace_id and value.session_id == session_id
        )


class DissentGraph:
    def __init__(self, nodes: tuple[GraphNode, ...] = ()) -> None:
        self.nodes = {node.ref_id: node for node in nodes}

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        node = self.nodes.get(artifact_id)
        if node is None or node.workspace_id != workspace_id or node.session_id != session_id:
            return None
        return node

    async def trace_backward(
        self,
        workspace_id: UUID,
        session_id: UUID,
        node_id: UUID,
        **kwargs: Any,
    ) -> TraversalResult:
        del kwargs
        nodes = tuple(
            node
            for node in self.nodes.values()
            if node.workspace_id == workspace_id
            and node.session_id == session_id
            and node.id == node_id
        )
        return TraversalResult(nodes=nodes)

    async def subgraph(self, *args: Any, **kwargs: Any) -> TraversalResult:
        del args, kwargs
        return TraversalResult()


@req("FR-311", "FR-504", "FR-705", "FR-708", "FR-805", "NFR-005", "NFR-019")
@pytest.mark.parametrize("role", list(WorkspaceRole))
def test_assumption_register_all_roles_and_authentication(role: WorkspaceRole) -> None:
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], role)
    handoff = CritiqueExplanationHandoff(
        workspace_id=U[1],
        session_id=U[2],
        entries=(),
        empty_reason=CritiqueHandoffEmptyReason.NO_COMPLETED_CRITIC_RUN,
    )
    tx = Tx(
        Artifacts(),
        Idempotency(),
        sessions=DissentSessions(),
        graph=DissentGraph(),
        critique_handoffs=DissentHandoffs(handoff),
        assumption_register=EmptyAssumptionRegister(),
    )
    client, _ = _client_for(principal, tx)
    path = f"/api/v1/sessions/{public_id('session', U[2])}/assumptions"
    with client:
        assert client.get(path).status_code == 401
        response = client.get(path, headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "session_id": public_id("session", U[2]),
        "items": [],
    }


@req("NFR-005", "NFR-019")
def test_assumption_register_hides_missing_or_cross_tenant_session() -> None:
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.VIEWER)
    tx = Tx(
        Artifacts(),
        Idempotency(),
        sessions=DissentSessions(visible=False),
        graph=DissentGraph(),
        assumption_register=EmptyAssumptionRegister(),
    )
    client, _ = _client_for(principal, tx)
    with client:
        response = client.get(
            f"/api/v1/sessions/{public_id('session', U[2])}/assumptions",
            headers={"Authorization": "Bearer valid"},
        )
    assert response.status_code == 404


def _consensus(result_id: UUID, round_number: int) -> ConsensusRunRecord:
    return ConsensusRunRecord(
        id=result_id,
        workspace_id=U[1],
        session_id=U[2],
        round=round_number,
        strategy="weighted",
        strategy_version="2",
        outcome=ConsensusOutcome.PARTIAL_CONSENSUS,
        selected_alternative_id=U[6],
        input_hash="sha256:" + "a" * 64,
        created_at=NOW,
    )


@req("FR-504", "FR-505", "FR-506", "FR-609", "FR-901", "NFR-005", "NFR-019")
def test_dissent_route_projects_latest_persisted_explanation_and_open_critiques() -> None:
    warrant = claim()
    selected_values = warrant.model_dump(mode="python")
    selected_values.update(
        {
            "id": U[6],
            "logical_id": U[6],
            "kind": ArtifactKind.ALTERNATIVE,
            "payload": AlternativePayload(
                name="Safer option",
                summary="Lower risk",
                components=("staged rollout",),
                origin="fixture",
                feasibility_status="SAT",
            ),
        }
    )
    selected_values["content_hash"] = artifact_content_hash(selected_values)
    selected = validate_artifact(selected_values)
    node = GraphNode(
        id=U[5],
        workspace_id=U[1],
        session_id=U[2],
        kind=warrant.kind,
        ref_id=warrant.id,
        label="Cost concern",
    )
    selected_node = GraphNode(
        id=U[6],
        workspace_id=U[1],
        session_id=U[2],
        kind=selected.kind,
        ref_id=selected.id,
        label="Safer option",
    )
    older, latest = _consensus(U[7], 1), _consensus(U[8], 2)
    explanation = ConsensusExplanation(
        consensus_id=latest.id,
        outcome=latest.outcome,
        strategy=latest.strategy,
        strategy_version=latest.strategy_version,
        formula="persisted",
        minority_report=(
            MinorityEntry(
                agent_id=U[4],
                position="Prefer the safer option",
                warrant_artifact_ids=(warrant.id,),
                disputed_propositions=(U[3],),
                unresolved_critiques=(U[0],),
            ),
        ),
        input_hash=latest.input_hash,
    )
    handoff = CritiqueExplanationHandoff(
        workspace_id=U[1],
        session_id=U[2],
        entries=(
            CritiqueExplanationEntry(
                critique_id=U[0],
                logical_id=U[0],
                version=1,
                target_artifact_id=U[6],
                critique_type=CritiqueType.EVIDENCE_GAP,
                severity=Severity.HIGH,
                resolution=Resolution.OPEN,
                creation_ledger_seq=1,
            ),
        ),
    )
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.VIEWER)
    tx = Tx(
        DissentArtifacts((warrant, selected)),
        Idempotency(),
        sessions=DissentSessions(),
        graph=DissentGraph((node, selected_node)),
        consensus_results=DissentConsensus((latest, older), {}),
        dissent_explanations=DissentConsensus((), {latest.id: explanation}),
        critique_handoffs=DissentHandoffs(handoff),
        citations=ProvenanceCitations(),
    )
    client, _ = _client_for(principal, tx)
    with client:
        response = client.get(
            f"/api/v1/sessions/{public_id('session', U[2])}/dissent",
            headers={"Authorization": "Bearer valid"},
        )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["evaluated"] is True
    assert data["empty_reason"] is None
    assert data["majority"] == {
        "consensus_result_id": public_id("consensus_result", latest.id),
        "outcome": "PARTIAL_CONSENSUS",
        "selected_alternative_id": public_id("artifact", U[6]),
        "selected_alternative_label": "Safer option",
        "selected_alternative_graph_node_id": public_id("graph_node", selected_node.id),
        "selected_alternative_provenance_href": (
            f"/api/v1/artifacts/{public_id('artifact', U[6])}/provenance"
        ),
        "strategy": "weighted",
        "strategy_version": "2",
        "round": 2,
    }
    assert data["minority"][0]["agent_id"] == public_id("agent", U[4])
    assert data["evidence_context"] == {
        "supports_selected": [],
        "opposes_selected": [],
        "qualifies_selected": [],
    }
    assert data["minority"][0]["what_would_change"] is None
    assert data["minority"][0]["warrants"][0] == {
        "id": public_id("artifact", warrant.id),
        "kind": "CLAIM",
        "label": "Cost concern",
        "lifecycle": "ACTIVE",
        "graph_node_id": public_id("graph_node", node.id),
        "provenance_href": f"/api/v1/artifacts/{public_id('artifact', warrant.id)}/provenance",
    }
    assert data["critiques"][0]["critique_id"] == public_id("critique", U[0])
    assert data["critiques"][0]["critique_artifact_id"] == public_id("artifact", U[0])
    assert data["critiques"][0]["provenance_href"] == (
        f"/api/v1/artifacts/{public_id('artifact', U[0])}/provenance"
    )
    assert "support" not in data["majority"]
    assert "dissent" not in data["majority"]


@req("FR-505", "FR-609", "NFR-019")
@pytest.mark.parametrize(
    ("results", "explanations", "evaluated", "empty_reason"),
    [
        ((), {}, False, "NO_CONSENSUS_RESULT"),
        ((_consensus(U[7], 1),), {}, False, "CONSENSUS_EXPLANATION_UNAVAILABLE"),
    ],
)
def test_dissent_route_has_explicit_unevaluated_empty_states(
    results: tuple[ConsensusRunRecord, ...],
    explanations: dict[UUID, ConsensusExplanation],
    evaluated: bool,
    empty_reason: str,
) -> None:
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.VIEWER)
    handoff = CritiqueExplanationHandoff(
        workspace_id=U[1],
        session_id=U[2],
        entries=(),
        empty_reason=CritiqueHandoffEmptyReason.NO_COMPLETED_CRITIC_RUN,
    )
    tx = Tx(
        DissentArtifacts(),
        Idempotency(),
        sessions=DissentSessions(),
        graph=DissentGraph(),
        consensus_results=DissentConsensus(results, {}),
        dissent_explanations=DissentConsensus((), explanations),
        critique_handoffs=DissentHandoffs(handoff),
        citations=ProvenanceCitations(),
    )
    client, _ = _client_for(principal, tx)
    path = f"/api/v1/sessions/{public_id('session', U[2])}/dissent"
    with client:
        response = client.get(path, headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200
    assert response.json()["data"]["evaluated"] is evaluated
    assert response.json()["data"]["empty_reason"] == empty_reason


@req("FR-505", "FR-609", "NFR-005", "NFR-019")
def test_dissent_route_reports_evaluated_no_dissent_and_hides_unknown_session() -> None:
    result = _consensus(U[7], 1)
    result = result.model_copy(update={"selected_alternative_id": None})
    explanation = ConsensusExplanation(
        consensus_id=result.id,
        outcome=result.outcome,
        strategy=result.strategy,
        strategy_version=result.strategy_version,
        formula="persisted",
        input_hash=result.input_hash,
    )
    handoff = CritiqueExplanationHandoff(
        workspace_id=U[1],
        session_id=U[2],
        entries=(),
        empty_reason=CritiqueHandoffEmptyReason.COMPLETED_CRITIC_RUN_WITHOUT_CRITIQUES,
    )
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.VIEWER)
    tx = Tx(
        DissentArtifacts(),
        Idempotency(),
        sessions=DissentSessions(),
        graph=DissentGraph(),
        consensus_results=DissentConsensus((result,), {}),
        dissent_explanations=DissentConsensus((), {result.id: explanation}),
        critique_handoffs=DissentHandoffs(handoff),
        citations=ProvenanceCitations(),
    )
    client, _ = _client_for(principal, tx)
    path = f"/api/v1/sessions/{public_id('session', U[2])}/dissent"
    with client:
        response = client.get(path, headers={"Authorization": "Bearer valid"})
        tx.sessions = DissentSessions(visible=False)
        hidden = client.get(path, headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200
    assert response.json()["data"]["evaluated"] is True
    assert response.json()["data"]["empty_reason"] == "EVALUATED_NO_DISSENT"
    assert hidden.status_code == 404


@req("FR-504", "FR-505", "FR-605", "FR-609", "FR-804", "FR-805", "FR-901", "NFR-005", "NFR-019")
@pytest.mark.parametrize("role", list(WorkspaceRole))
def test_explanation_route_composes_persisted_decision_for_every_role(role: WorkspaceRole) -> None:
    selected_values = claim().model_dump(mode="python")
    selected_values.update(
        id=U[6],
        logical_id=U[6],
        kind=ArtifactKind.ALTERNATIVE,
        payload=AlternativePayload(
            name="Selected",
            summary="Selected persisted option",
            components=("one",),
            origin="fixture",
            feasibility_status="SAT",
        ),
    )
    selected_values["content_hash"] = artifact_content_hash(selected_values)
    selected = validate_artifact(selected_values)
    latest = _consensus(U[8], 2)
    explanation = ConsensusExplanation(
        consensus_id=latest.id,
        outcome=latest.outcome,
        strategy=latest.strategy,
        strategy_version=latest.strategy_version,
        formula="sum(weight * position)",
        caveats=("Support is not confidence or probability.",),
        minority_report=(MinorityEntry(agent_id=U[4], position="OPPOSE"),),
        input_hash=latest.input_hash,
    )
    handoff = CritiqueExplanationHandoff(
        workspace_id=U[1],
        session_id=U[2],
        entries=(),
        empty_reason=CritiqueHandoffEmptyReason.NO_COMPLETED_CRITIC_RUN,
    )
    recommendation = PersistedRecommendation(
        id=U[7],
        alternative_id=selected.id,
        rank=1,
        title="Adopt selected",
        statement="Proceed",
        conditions=(),
        risk_ids=(),
        open_questions=(),
        is_override=False,
        override_by=None,
        override_reason=None,
    )
    tx = Tx(
        DissentArtifacts((selected,)),
        Idempotency(),
        sessions=DissentSessions(),
        graph=DissentGraph(
            (
                GraphNode(
                    id=U[5],
                    workspace_id=U[1],
                    session_id=U[2],
                    kind=selected.kind,
                    ref_id=selected.id,
                    label="Selected",
                ),
            )
        ),
        citations=ProvenanceCitations(),
        dissent_explanations=DissentConsensus((), {latest.id: explanation}),
        critique_handoffs=DissentHandoffs(handoff),
        assumption_register=EmptyAssumptionRegister(),
        decision_explanations=ExplanationReader(
            DecisionExplanationSnapshot(latest, (recommendation,), (selected,), ())
        ),
    )
    client, _ = _client_for(VerifiedPrincipal("oidc|u", U[4], U[1], role), tx)
    path = f"/api/v1/sessions/{public_id('session', U[2])}/explanation"
    with client:
        assert client.get(path).status_code == 401
        response = client.get(path, headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "AVAILABLE"
    assert data["decision"]["round"]["kind"] == "consensus_round"
    assert data["recommendation"]["items"][0]["id"] == public_id("recommendation", U[7])
    assert data["why"]["formula"] == "sum(weight * position)"
    assert data["why"]["drivers"]["empty_reason"] == "NO_PERSISTED_SUPPORTING_DRIVERS"
    assert data["why"]["inhibitors"]["empty_reason"] == "NO_PERSISTED_INHIBITORS"
    assert data["why"]["absent"]["empty_reason"] == (
        "NO_PERSISTED_ABSENT_EVIDENCE_OR_OPEN_QUESTIONS"
    )
    assert data["minority"][0]["position"] == "OPPOSE"
    assert data["weakest_evidence"]["available"] is False
    assert data["links"]["dissent"] == "#/dissent"
    assert data["links"]["assumptions"] == "#/assumptions"


@req("FR-605", "NFR-005", "NFR-019")
@pytest.mark.parametrize(
    ("latest", "explanations", "reason"),
    [(None, {}, "NO_CONSENSUS_RESULT"), (_consensus(U[8], 2), {}, "EXPLANATION_UNAVAILABLE")],
)
def test_explanation_route_returns_explicit_unavailable_states(
    latest: Any, explanations: Any, reason: str
) -> None:
    handoff = CritiqueExplanationHandoff(
        workspace_id=U[1],
        session_id=U[2],
        entries=(),
        empty_reason=CritiqueHandoffEmptyReason.NO_COMPLETED_CRITIC_RUN,
    )
    tx = Tx(
        DissentArtifacts(),
        Idempotency(),
        sessions=DissentSessions(),
        graph=DissentGraph(),
        citations=ProvenanceCitations(),
        dissent_explanations=DissentConsensus((), explanations),
        critique_handoffs=DissentHandoffs(handoff),
        assumption_register=EmptyAssumptionRegister(),
        decision_explanations=ExplanationReader(DecisionExplanationSnapshot(latest, (), (), ())),
    )
    client, _ = _client_for(VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.VIEWER), tx)
    with client:
        response = client.get(
            f"/api/v1/sessions/{public_id('session', U[2])}/explanation",
            headers={"Authorization": "Bearer valid"},
        )
    assert response.status_code == 200
    assert response.json()["data"]["empty_reason"] == reason
    assert set(response.json()["data"]) >= {
        "decision",
        "recommendation",
        "why",
        "alternatives",
        "evidence",
        "assumptions_constraints",
        "minority",
        "critiques",
        "risks_uncertainties",
        "symbolic_feasibility",
        "conditions_counterfactuals",
        "weakest_evidence",
        "provenance",
        "links",
    }


@req("FR-305")
def test_revision_replays_original_response_and_rejects_changed_request() -> None:
    artifact = claim()
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.RESEARCHER)
    idempotency = Idempotency()
    body = _revision_body()
    request_hash = content_hash(
        {
            "if_match": 1,
            "body": ArtifactRevisionCreate.model_validate(body).model_dump(mode="json"),
        }
    )
    original = {"data": {"id": public_id("artifact", U[5])}, "meta": {"version": 2}}
    operation = f"artifact:revise:{artifact.id}"
    idempotency.values[(principal.workspace_id, operation, "same-key")] = IdempotencyRecord(
        request_hash=request_hash, status_code=201, response_body=original
    )
    client, _ = _client_for(principal, Tx(Artifacts(artifact), idempotency))
    headers = {
        "Authorization": "Bearer valid",
        "Idempotency-Key": "same-key",
        "If-Match": "1",
    }
    with client:
        replay = client.post(
            f"/api/v1/artifacts/{public_id('artifact', artifact.id)}/revisions",
            headers=headers,
            json=body,
        )
        changed = client.post(
            f"/api/v1/artifacts/{public_id('artifact', artifact.id)}/revisions",
            headers=headers,
            json=_revision_body("Different replacement"),
        )
    assert replay.status_code == 201
    assert replay.json() == original
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.headers["ETag"] == "2"
    assert changed.status_code == 409
    assert changed.json()["code"] == "VERSION_CONFLICT"


@req("FR-305")
def test_revision_rejects_stale_if_match_with_current_version() -> None:
    artifact = claim()
    principal = VerifiedPrincipal("oidc|u", U[4], U[1], WorkspaceRole.RESEARCHER)
    client, _ = _client_for(principal, Tx(Artifacts(artifact), Idempotency()))
    with client:
        response = client.post(
            f"/api/v1/artifacts/{public_id('artifact', artifact.id)}/revisions",
            headers={
                "Authorization": "Bearer valid",
                "Idempotency-Key": "stale",
                "If-Match": "2",
            },
            json=_revision_body(),
        )
    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"
    assert response.json()["current_version"] == 1
