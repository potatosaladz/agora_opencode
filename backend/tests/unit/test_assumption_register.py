"""Focused T14-03 assumption-register API composition tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest

from app.application.assumption_register import AssumptionRegisterService
from app.common.ids import public_id
from app.domain.assumption_register import AssumptionRegisterSnapshot, ConstraintAnalysis
from app.domain.critique_handoff import (
    CritiqueExplanationEntry,
    CritiqueExplanationHandoff,
    CritiqueExplanationHandoffReader,
    CritiqueHandoffEmptyReason,
)
from app.domain.formalization import (
    BooleanLiteral,
    FormalizationDecision,
    FormalizationDecisionKind,
    FormalizationRevision,
    FormalizationValidation,
    ast_hash,
)
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    AssumptionPayload,
    ConstraintPayload,
    ConstraintType,
    CritiqueType,
    FormalExpression,
    GraphEdgeType,
    LifecycleStatus,
    Provenance,
    ProvenanceOrigin,
    Resolution,
    Severity,
    artifact_content_hash,
    validate_artifact,
)
from app.domain.reasoning_graph import GraphEdge, GraphNode, ReasoningGraphStore, TraversalResult
from app.domain.symbolic_evaluation import SymbolicEvaluation, symbolic_evaluation_hash
from app.ports.symbolic import SymbolicCoreMember, SymbolicReasoningResult, SymbolicStatus
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 20))
NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _artifact(
    artifact_id: UUID,
    logical_id: UUID,
    kind: ArtifactKind,
    payload: Any,
    *,
    version: int = 1,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    supersedes_id: UUID | None = None,
) -> Any:
    values = {
        "id": artifact_id,
        "workspace_id": U[0],
        "session_id": U[1],
        "logical_id": logical_id,
        "kind": kind,
        "version": version,
        "status": status,
        "supersedes_id": supersedes_id,
        "owner_actor_class": ActorClass.AGENT,
        "owner_actor_id": U[2],
        "round": 2,
        "payload": payload,
        "provenance": Provenance(origin=ProvenanceOrigin.LLM, reference="fixture"),
        "created_at": NOW,
        "updated_at": NOW,
        "content_hash": "",
    }
    values["content_hash"] = artifact_content_hash(values)
    return validate_artifact(values)


class Reader:
    def __init__(self, snapshot: AssumptionRegisterSnapshot) -> None:
        self.snapshot = snapshot

    async def read(self, workspace_id: UUID, session_id: UUID) -> AssumptionRegisterSnapshot:
        assert (workspace_id, session_id) == (U[0], U[1])
        return self.snapshot


class Graph:
    def __init__(self, result: TraversalResult) -> None:
        self.result = result
        self.calls = 0

    async def subgraph(self, *args: Any, **kwargs: Any) -> TraversalResult:
        self.calls += 1
        return self.result


class Handoffs:
    def __init__(self, handoff: CritiqueExplanationHandoff) -> None:
        self.handoff = handoff

    async def read(self, workspace_id: UUID, session_id: UUID) -> CritiqueExplanationHandoff:
        assert (workspace_id, session_id) == (U[0], U[1])
        return self.handoff


@req("FR-311", "FR-504", "FR-705", "FR-708", "FR-805", "NFR-005", "NFR-010", "NFR-019")
@pytest.mark.asyncio
async def test_register_is_complete_ordered_public_and_marks_missing_symbolic_analysis() -> None:
    old = _artifact(
        U[3],
        U[4],
        ArtifactKind.ASSUMPTION,
        AssumptionPayload(
            statement="Demand holds",
            basis="Survey",
            materiality="Changes volume",
            challengeable=True,
        ),
        status=LifecycleStatus.SUPERSEDED,
    )
    current = _artifact(
        U[5],
        U[4],
        ArtifactKind.ASSUMPTION,
        AssumptionPayload(
            statement="Demand still holds",
            basis="Survey update",
            materiality="Changes volume",
            challengeable=True,
        ),
        version=2,
        supersedes_id=old.id,
    )
    constraint = _artifact(
        U[6],
        U[6],
        ArtifactKind.CONSTRAINT,
        ConstraintPayload(
            name="Budget",
            statement="Spend below limit",
            constraint_type=ConstraintType.NON_NEGOTIABLE,
            category="financial",
            evaluation_expression=FormalExpression(language="agora", ast={"op": "le"}),
            formal_status="CANDIDATE",
        ),
        status=LifecycleStatus.WITHDRAWN,
    )
    critique_id = U[7]
    nodes = tuple(
        GraphNode(
            id=U[index],
            workspace_id=U[0],
            session_id=U[1],
            kind=artifact.kind,
            ref_id=artifact.id,
            label=artifact.kind.value,
        )
        for index, artifact in zip((10, 11, 12), (old, current, constraint), strict=True)
    )
    critique_node = GraphNode(
        id=U[13],
        workspace_id=U[0],
        session_id=U[1],
        kind=ArtifactKind.CRITIQUE,
        ref_id=critique_id,
        label="Challenge",
    )
    edge = GraphEdge(
        id=U[14],
        workspace_id=U[0],
        session_id=U[1],
        from_node=nodes[1].id,
        to_node=nodes[0].id,
        edge_type=GraphEdgeType.SUPERSEDES,
        actor_class=ActorClass.AGENT,
        actor_id=U[2],
    )
    handoff = CritiqueExplanationHandoff(
        workspace_id=U[0],
        session_id=U[1],
        entries=(
            CritiqueExplanationEntry(
                critique_id=critique_id,
                logical_id=critique_id,
                version=1,
                target_artifact_id=current.id,
                critique_type=CritiqueType.EVIDENCE_GAP,
                severity=Severity.HIGH,
                resolution=Resolution.OPEN,
                creation_ledger_seq=1,
            ),
        ),
    )
    snapshot = AssumptionRegisterSnapshot(
        artifacts=(old, current, constraint),
        graph_nodes=(*nodes, critique_node),
        constraint_analyses=(),
        recommendations=(),
    )
    graph = Graph(TraversalResult(nodes=(*nodes, critique_node), edges=(edge,)))

    result = await AssumptionRegisterService(
        Reader(snapshot),
        cast(ReasoningGraphStore, graph),
        cast(CritiqueExplanationHandoffReader, Handoffs(handoff)),
    ).read(U[0], U[1], request_id="req_test")
    body = result
    items = body["data"]["items"]

    assert [item["id"] for item in items] == [
        public_id("artifact", old.id),
        public_id("artifact", current.id),
        public_id("artifact", constraint.id),
    ]
    assert [item["lifecycle"] for item in items] == ["SUPERSEDED", "ACTIVE", "WITHDRAWN"]
    assert items[1]["critiques"][0]["id"] == public_id("critique", critique_id)
    assert items[2]["constraint_type"] == "NON_NEGOTIABLE"
    assert items[2]["symbolic"] == {
        "analysis_status": "MISSING_FORMALIZATION",
        "formalization": None,
        "evaluation_id": None,
        "status": None,
        "reason": "No formalization exists for this exact constraint revision.",
        "policy_action": "DEFER",
    }
    assert graph.calls == 1
    assert str(U[0]) not in str(body)
    assert str(U[1]) not in str(body)


@req("FR-705", "FR-708", "NFR-005")
@pytest.mark.parametrize(
    ("status", "reason_unknown", "action"),
    [
        (SymbolicStatus.SAT, None, "PROCEED"),
        (SymbolicStatus.UNSAT, None, "BLOCK"),
        (SymbolicStatus.UNKNOWN, "timeout", "DEFER"),
    ],
)
@pytest.mark.asyncio
async def test_constraint_preserves_symbolic_status_and_safe_policy(
    status: SymbolicStatus, reason_unknown: str | None, action: str
) -> None:
    constraint = _artifact(
        U[6],
        U[6],
        ArtifactKind.CONSTRAINT,
        ConstraintPayload(
            name="Budget",
            statement="Spend below limit",
            constraint_type=ConstraintType.HARD,
            category="financial",
            evaluation_expression=FormalExpression(language="agora", ast={"op": "le"}),
            formal_status="VALIDATED",
        ),
    )
    ast = BooleanLiteral(value=True)
    formalization = FormalizationRevision(
        id=U[7],
        logical_id=U[8],
        revision=1,
        supersedes_id=None,
        workspace_id=U[0],
        session_id=U[1],
        source_artifact_id=constraint.id,
        source_artifact_logical_id=constraint.logical_id,
        source_artifact_version=constraint.version,
        ast=ast,
        ast_hash=ast_hash(ast),
        symbols=(),
        canonical_rendering="true",
        premise_artifact_ids=(),
        limitations=("Fixture",),
        fidelity_notes="Exact fixture",
        created_at=NOW,
        actor_class=ActorClass.HUMAN,
        actor_id=U[2],
        correlation_id=U[9],
    )
    symbolic_result = SymbolicReasoningResult(
        status=status,
        formalization_revision_id=formalization.id,
        ast_hash=formalization.ast_hash,
        solver="z3",
        solver_version="1",
        timeout_ms=100,
        configuration_id="default",
        reason_unknown=reason_unknown,
        unsat_core=(SymbolicCoreMember("ast"),) if status is SymbolicStatus.UNSAT else (),
    )
    evaluation = SymbolicEvaluation(
        id=U[10],
        workspace_id=U[0],
        session_id=U[1],
        result=symbolic_result,
        evidence_hash=symbolic_evaluation_hash(symbolic_result),
        evaluated_at=NOW,
        actor_id=U[2],
        correlation_id=U[9],
    )
    validation = FormalizationValidation(
        id=U[11],
        workspace_id=U[0],
        formalization_revision_id=formalization.id,
        ast_hash=formalization.ast_hash,
        validator_ruleset="test",
        success=True,
        issues=(),
        validated_at=NOW,
        actor_class=ActorClass.HUMAN,
        actor_id=U[2],
        correlation_id=U[9],
    )
    decision = FormalizationDecision(
        id=U[12],
        workspace_id=U[0],
        formalization_revision_id=formalization.id,
        ast_hash=formalization.ast_hash,
        kind=FormalizationDecisionKind.CONFIRMED,
        reason="Reviewed",
        decided_at=NOW,
        actor_id=U[2],
        correlation_id=U[9],
    )
    node = GraphNode(
        id=U[13],
        workspace_id=U[0],
        session_id=U[1],
        kind=constraint.kind,
        ref_id=constraint.id,
        label="Budget",
    )
    snapshot = AssumptionRegisterSnapshot(
        artifacts=(constraint,),
        graph_nodes=(node,),
        constraint_analyses=(
            (
                constraint.id,
                ConstraintAnalysis(formalization, validation, decision, evaluation),
            ),
        ),
        recommendations=(),
    )
    handoff = CritiqueExplanationHandoff(
        workspace_id=U[0],
        session_id=U[1],
        entries=(),
        empty_reason=CritiqueHandoffEmptyReason.NO_COMPLETED_CRITIC_RUN,
    )

    body = await AssumptionRegisterService(
        Reader(snapshot),
        cast(ReasoningGraphStore, Graph(TraversalResult(nodes=(node,)))),
        cast(CritiqueExplanationHandoffReader, Handoffs(handoff)),
    ).read(U[0], U[1], request_id="req_test")
    symbolic = body["data"]["items"][0]["symbolic"]

    assert symbolic["status"] == status.value
    assert symbolic["policy_action"] == action
    assert symbolic["reason"] == (
        reason_unknown
        if reason_unknown is not None
        else {
            SymbolicStatus.SAT: (
                "The symbolic constraints are satisfiable under the encoded premises."
            ),
            SymbolicStatus.UNSAT: "A contradiction was established under the encoded premises.",
        }[status]
    )
    assert symbolic["formalization"]["source_artifact_version"] == constraint.version
    assert symbolic["evaluation_id"] == public_id("symbolic_evaluation", evaluation.id)
