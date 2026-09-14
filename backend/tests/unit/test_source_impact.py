"""Source-impact contract, service, and public API tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import create_app
from app.application.source_impact import SourceImpactService
from app.common.ids import public_id
from app.config import Settings
from app.domain.citations import CitationSnapshot, EvidenceCitation, SourceRetractionCommand
from app.domain.knowledge import SourceStatus
from app.domain.reasoning import ActorClass, ArtifactKind, GraphEdgeType
from app.domain.reasoning_graph import GraphEdge, GraphNode, TraversalResult
from app.domain.source_impact import (
    ImpactAnalysisResult,
    ImpactAnalysisStatus,
    ImpactDependency,
    ImpactDependencyType,
    SourceImpactReport,
    SourceImpactRepository,
)
from app.ports.auth import VerifiedPrincipal, WorkspaceRole
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{index:012d}") for index in range(1, 16))
NOW = datetime(2026, 9, 11, 12, tzinfo=UTC)


def report() -> SourceImpactReport:
    dependencies = (
        ImpactDependency(
            dependency_type=ImpactDependencyType.ARTIFACT,
            dependent_id=U[6],
            session_id=U[5],
            root_evidence_id=U[13],
            artifact_kind=ArtifactKind.CLAIM,
            logical_id=U[7],
            artifact_version=2,
            min_depth=1,
            path_count=3,
            evidence_weight=Decimal("2.5"),
        ),
        ImpactDependency(
            dependency_type=ImpactDependencyType.ARTIFACT,
            dependent_id=U[8],
            session_id=U[5],
            root_evidence_id=U[13],
            artifact_kind=ArtifactKind.ALTERNATIVE,
            logical_id=U[9],
            artifact_version=1,
            min_depth=2,
            path_count=2,
            evidence_weight=Decimal("1.5"),
        ),
        ImpactDependency(
            dependency_type=ImpactDependencyType.CONSENSUS_RESULT,
            dependent_id=U[10],
            session_id=U[5],
            root_evidence_id=U[13],
            min_depth=3,
            path_count=2,
            evidence_weight=Decimal("1.5"),
        ),
        ImpactDependency(
            dependency_type=ImpactDependencyType.RECOMMENDATION,
            dependent_id=U[11],
            session_id=U[5],
            root_evidence_id=U[13],
            min_depth=4,
            path_count=2,
            evidence_weight=Decimal("1.5"),
        ),
    )
    return SourceImpactReport(
        report_id=U[0],
        retraction_id=U[1],
        event_id=U[2],
        workspace_id=U[3],
        source_id=U[4],
        actor_id=U[12],
        reason="publisher correction",
        generated_at=NOW,
        analysis_status=ImpactAnalysisStatus.COMPLETE,
        complete=True,
        truncated=False,
        dependencies=dependencies,
    )


class ImpactStore:
    def __init__(self) -> None:
        self.value = report()
        self.commands: list[SourceRetractionCommand] = []
        self.graph = ImpactGraph()

    async def lock_source_for_analysis(self, workspace_id: UUID, source_id: UUID) -> None:
        assert (workspace_id, source_id) == (U[3], U[4])

    async def retract_and_report(
        self,
        command: SourceRetractionCommand,
        *,
        report_id: UUID,
        event_id: UUID,
        correlation_id: UUID,
        analysis: ImpactAnalysisResult,
    ) -> SourceImpactReport:
        del report_id, event_id, correlation_id, analysis
        self.commands.append(command)
        return self.value

    async def get_report(self, workspace_id: UUID, report_id: UUID) -> SourceImpactReport | None:
        if workspace_id == self.value.workspace_id and report_id == self.value.report_id:
            return self.value
        return None

    async def citation_roots(
        self, workspace_id: UUID, source_id: UUID
    ) -> tuple[EvidenceCitation, ...]:
        del workspace_id, source_id
        return (
            EvidenceCitation(
                citation_id=U[14],
                workspace_id=U[3],
                session_id=U[5],
                evidence_artifact_id=U[13],
                claim_artifact_id=U[6],
                actor_id=U[12],
                attached_at=NOW,
                snapshot=CitationSnapshot(
                    namespace_id=U[0],
                    source_id=U[4],
                    document_id=U[1],
                    chunk_id=U[2],
                    citation="Fixture source",
                    locator={"char_start": 0, "char_end": 1},
                    source_content_hash="sha256:" + "a" * 64,
                    chunk_content_hash="sha256:" + "b" * 64,
                    chunker_version="fixture-v1",
                    source_timestamp=NOW,
                    document_timestamp=NOW,
                    retrieved_at=NOW,
                    trust_level="PRIMARY",
                    source_status=SourceStatus.READY,
                ),
            ),
        )

    async def downstream_records(
        self, workspace_id: UUID, artifacts: tuple[ImpactDependency, ...]
    ) -> tuple[ImpactDependency, ...]:
        del workspace_id
        assert {item.dependent_id for item in artifacts} == {U[13], U[6], U[8]}
        return self.value.dependencies[2:]

    async def artifact_dependencies(
        self,
        workspace_id: UUID,
        reached: tuple[tuple[GraphNode, UUID, int, int], ...],
    ) -> tuple[ImpactDependency, ...]:
        del workspace_id, reached
        return (
            ImpactDependency(
                dependency_type=ImpactDependencyType.ARTIFACT,
                dependent_id=U[13],
                session_id=U[5],
                root_evidence_id=U[13],
                artifact_kind=ArtifactKind.EVIDENCE,
                logical_id=U[13],
                artifact_version=1,
                min_depth=0,
                path_count=1,
                evidence_weight=Decimal(1),
            ),
            *self.value.dependencies[:2],
        )


class ImpactGraph:
    def __init__(self) -> None:
        self.evidence = GraphNode(
            id=U[13],
            workspace_id=U[3],
            session_id=U[5],
            kind=ArtifactKind.EVIDENCE,
            ref_id=U[13],
            label="Evidence",
            attrs={"logical_id": str(U[13]), "version": 1},
        )
        self.claim = GraphNode(
            id=U[6],
            workspace_id=U[3],
            session_id=U[5],
            kind=ArtifactKind.CLAIM,
            ref_id=U[6],
            label="Claim",
            attrs={"logical_id": str(U[7]), "version": 2},
        )
        self.alternative = GraphNode(
            id=U[8],
            workspace_id=U[3],
            session_id=U[5],
            kind=ArtifactKind.ALTERNATIVE,
            ref_id=U[8],
            label="Alternative",
            attrs={"logical_id": str(U[9]), "version": 1},
        )

    async def node_for_artifact(
        self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
    ) -> GraphNode | None:
        del workspace_id, session_id
        return self.evidence if artifact_id == self.evidence.ref_id else None

    async def trace_forward(self, *args: Any, **kwargs: Any) -> TraversalResult:
        del args, kwargs
        return TraversalResult(
            nodes=(self.evidence, self.claim, self.alternative),
            edges=(
                GraphEdge(
                    id=U[0],
                    workspace_id=U[3],
                    session_id=U[5],
                    from_node=U[13],
                    to_node=U[6],
                    edge_type=GraphEdgeType.SUPPORTS,
                    actor_class=ActorClass.HUMAN,
                    actor_id=U[12],
                ),
                GraphEdge(
                    id=U[1],
                    workspace_id=U[3],
                    session_id=U[5],
                    from_node=U[6],
                    to_node=U[8],
                    edge_type=GraphEdgeType.DERIVED_FROM,
                    actor_class=ActorClass.HUMAN,
                    actor_id=U[12],
                ),
            ),
        )


@req("FR-408")
async def test_service_returns_every_ranked_dependency() -> None:
    store = ImpactStore()
    repository = cast(SourceImpactRepository, store)
    assert isinstance(repository, SourceImpactRepository)
    result = await SourceImpactService(repository).impact_of(U[3], U[4])
    assert result.complete is True
    assert tuple(item.dependent_id for item in result.dependencies) == (
        U[13],
        U[6],
        U[8],
        U[10],
        U[11],
    )


class SegmentedImpactGraph(ImpactGraph):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[UUID, str | None]] = []
        self.tail = GraphNode(
            id=U[2],
            workspace_id=U[3],
            session_id=U[5],
            kind=ArtifactKind.CLAIM,
            ref_id=U[2],
            label="Tail claim",
        )

    async def trace_forward(self, *args: Any, **kwargs: Any) -> TraversalResult:
        frontier = cast(UUID, args[2])
        cursor = cast(str | None, kwargs.get("cursor"))
        self.calls.append((frontier, cursor))
        if frontier == self.evidence.id:
            if cursor is None:
                return TraversalResult(
                    nodes=(self.evidence,),
                    truncated=True,
                    next_cursor="next",
                )
            return TraversalResult(
                nodes=(self.claim,),
                edges=(
                    GraphEdge(
                        id=U[0],
                        workspace_id=U[3],
                        session_id=U[5],
                        from_node=self.evidence.id,
                        to_node=self.claim.id,
                        edge_type=GraphEdgeType.SUPPORTS,
                        actor_class=ActorClass.HUMAN,
                        actor_id=U[12],
                    ),
                ),
                truncated=True,
            )
        return TraversalResult(
            nodes=(self.claim, self.tail),
            edges=(
                GraphEdge(
                    id=U[1],
                    workspace_id=U[3],
                    session_id=U[5],
                    from_node=self.claim.id,
                    to_node=self.tail.id,
                    edge_type=GraphEdgeType.SUPPORTS,
                    actor_class=ActorClass.HUMAN,
                    actor_id=U[12],
                ),
            ),
        )


@req("FR-408")
async def test_service_exhausts_cursors_and_continues_from_depth_frontier() -> None:
    store = ImpactStore()
    graph = SegmentedImpactGraph()
    store.graph = cast(Any, graph)
    result = await SourceImpactService(cast(SourceImpactRepository, store)).impact_of(U[3], U[4])
    assert result.complete
    assert graph.calls == [(U[13], None), (U[13], "next"), (U[6], None)]


@req("FR-408")
async def test_retraction_publishes_incomplete_report_instead_of_silently_aborting() -> None:
    store = ImpactStore()

    class MissingRootGraph(ImpactGraph):
        async def node_for_artifact(
            self, workspace_id: UUID, session_id: UUID, artifact_id: UUID
        ) -> GraphNode | None:
            del workspace_id, session_id, artifact_id
            return None

    store.graph = cast(Any, MissingRootGraph())
    published = await SourceImpactService(cast(SourceImpactRepository, store)).retract_source(
        SourceRetractionCommand(
            retraction_id=U[1],
            workspace_id=U[3],
            source_id=U[4],
            actor_id=U[12],
            reason="publisher correction",
            retracted_at=NOW,
        ),
        report_id=U[0],
        event_id=U[2],
        correlation_id=U[14],
    )
    assert published == store.value
    assert len(store.commands) == 1


class Verifier:
    def __init__(self, principal: VerifiedPrincipal) -> None:
        self.principal = principal

    async def verify(self, token: str) -> VerifiedPrincipal:
        del token
        return self.principal


class Idempotency:
    def __init__(self) -> None:
        self.values: dict[tuple[UUID, str, str], Any] = {}

    async def load_after_lock(self, workspace_id: UUID, operation: str, key: str) -> Any:
        return self.values.get((workspace_id, operation, key))

    async def save(self, workspace_id: UUID, operation: str, key: str, record: Any) -> None:
        self.values[(workspace_id, operation, key)] = record


@dataclass(slots=True)
class Transaction:
    source_impacts: ImpactStore
    idempotency: Idempotency


class Container:
    def __init__(self, base: Any, principal: VerifiedPrincipal, tx: Transaction) -> None:
        self.database = base.database
        self.readiness_checks = base.readiness_checks
        self.access_token_verifier = Verifier(principal)
        self._base = base
        self._tx = tx

    @asynccontextmanager
    async def reasoning_transaction(self, workspace_id: UUID) -> AsyncIterator[Transaction]:
        assert workspace_id == self.access_token_verifier.principal.workspace_id
        yield self._tx

    async def close(self) -> None:
        await self._base.close()


def settings() -> Settings:
    return Settings(environment="test", object_store="inmemory")


def client_for(principal: VerifiedPrincipal, tx: Transaction) -> tuple[TestClient, FastAPI]:
    async def builder(config: Settings) -> Any:
        from app.composition import build_container

        return Container(await build_container(config), principal, tx)

    app = create_app(settings(), container_builder=builder)
    return TestClient(app), app


@req("FR-408")
def test_retraction_and_report_routes_use_public_ids_roles_and_idempotency() -> None:
    principal = VerifiedPrincipal("oidc|u", U[12], U[3], WorkspaceRole.RESEARCHER)
    store, idempotency = ImpactStore(), Idempotency()
    client, _ = client_for(principal, Transaction(store, idempotency))
    headers = {"Authorization": "Bearer valid", "Idempotency-Key": "retract-source"}
    with client:
        created = client.post(
            f"/api/v1/sources/{public_id('source', U[4])}/retractions",
            headers=headers,
            json={"reason": "publisher correction"},
        )
        replayed = client.post(
            f"/api/v1/sources/{public_id('source', U[4])}/retractions",
            headers=headers,
            json={"reason": "publisher correction"},
        )
        loaded = client.get(
            f"/api/v1/impact-reports/{public_id('impact_report', U[0])}",
            headers={"Authorization": "Bearer valid"},
        )
    assert created.status_code == 201
    assert created.json()["data"]["id"] == public_id("impact_report", U[0])
    assert created.json()["data"]["affected_claim_ids"] == [public_id("artifact", U[6])]
    assert created.json()["data"]["affected_consensus_result_ids"] == [
        public_id("consensus_result", U[10])
    ]
    assert replayed.headers["Idempotency-Replayed"] == "true"
    assert len(store.commands) == 1
    assert loaded.status_code == 200
    assert loaded.json()["data"] == created.json()["data"]
    assert loaded.json()["meta"]["workspace_id"] == created.json()["meta"]["workspace_id"]
