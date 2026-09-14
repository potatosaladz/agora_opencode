"""Compose authoritative register facts through existing read boundaries."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.common.ids import public_id
from app.domain.assumption_register import AssumptionRegisterReader, ConstraintAnalysis
from app.domain.critique_handoff import CritiqueExplanationHandoffReader
from app.domain.formalization import derive_status
from app.domain.reasoning import (
    ArtifactKind,
    AssumptionPayload,
    ConstraintPayload,
    EvidencePayload,
    GraphEdgeType,
    ReasoningArtifact,
    Resolution,
    UncertaintyFields,
)
from app.domain.reasoning_graph import MAX_PAGE_SIZE, GraphEdge, ReasoningGraphStore
from app.domain.symbolic_unknown_policy import SymbolicAssuranceAction, SymbolicUnknownPolicy

__all__ = ["AssumptionRegisterService"]

_KINDS = {ArtifactKind.ASSUMPTION, ArtifactKind.CONSTRAINT, ArtifactKind.UNCERTAINTY}


def _actor_resource(value: str) -> str:
    return {"HUMAN": "user", "AGENT": "agent", "SERVICE": "service", "POLICY": "policy"}[value]


def _artifact_relation(artifact: ReasoningArtifact, node: Any, relationship: str) -> dict[str, Any]:
    encoded = public_id("artifact", artifact.id)
    return {
        "id": encoded,
        "kind": artifact.kind,
        "relationship": relationship,
        "label": node.label if node is not None else None,
        "graph_node_id": public_id("graph_node", node.id) if node is not None else None,
        "provenance_href": f"/api/v1/artifacts/{encoded}/provenance",
    }


def _symbolic(analysis: ConstraintAnalysis | None) -> dict[str, Any]:
    if analysis is None:
        return {
            "analysis_status": "MISSING_FORMALIZATION",
            "formalization": None,
            "evaluation_id": None,
            "status": None,
            "reason": "No formalization exists for this exact constraint revision.",
            "policy_action": SymbolicAssuranceAction.DEFER,
        }
    revision = analysis.formalization
    formalization = {
        "id": public_id("formalization", revision.logical_id),
        "revision_id": public_id("formalization", revision.id),
        "revision": revision.revision,
        "source_artifact_id": public_id("artifact", revision.source_artifact_id),
        "source_artifact_version": revision.source_artifact_version,
        "validation_status": derive_status(analysis.validation, analysis.decision),
    }
    evaluation = analysis.symbolic_evaluation
    if evaluation is None:
        return {
            "analysis_status": "MISSING_EVALUATION",
            "formalization": formalization,
            "evaluation_id": None,
            "status": None,
            "reason": "No persisted symbolic evaluation exists for this formalization revision.",
            "policy_action": SymbolicAssuranceAction.DEFER,
        }
    decision = SymbolicUnknownPolicy().decide(evaluation.result)
    return {
        "analysis_status": "AVAILABLE",
        "formalization": formalization,
        "evaluation_id": public_id("symbolic_evaluation", evaluation.id),
        "status": evaluation.result.status,
        "reason": evaluation.result.reason_unknown or decision.explanation,
        "policy_action": decision.action,
    }


class AssumptionRegisterService:
    def __init__(
        self,
        reader: AssumptionRegisterReader,
        graph: ReasoningGraphStore,
        critiques: CritiqueExplanationHandoffReader,
    ) -> None:
        self._reader = reader
        self._graph = graph
        self._critiques = critiques

    # trace: FR-311, FR-504, FR-705, FR-708, FR-805, NFR-005, NFR-010, NFR-019
    async def read(
        self, workspace_id: UUID, session_id: UUID, *, request_id: str
    ) -> dict[str, Any]:
        snapshot = await self._reader.read(workspace_id, session_id)
        artifacts = {artifact.id: artifact for artifact in snapshot.artifacts}
        nodes_by_artifact = {node.ref_id: node for node in snapshot.graph_nodes}
        nodes_by_id = {node.id: node for node in snapshot.graph_nodes}
        register = tuple(
            sorted(
                (artifact for artifact in snapshot.artifacts if artifact.kind in _KINDS),
                key=lambda artifact: (
                    artifact.kind.value,
                    artifact.logical_id.int,
                    artifact.version,
                    artifact.id.int,
                ),
            )
        )
        roots = tuple(
            nodes_by_artifact[artifact.id].id
            for artifact in register
            if artifact.id in nodes_by_artifact
        )
        edges: list[GraphEdge] = []
        cursor = None
        if roots:
            while True:
                page = await self._graph.subgraph(
                    workspace_id,
                    session_id,
                    roots,
                    max_depth=1,
                    page_size=MAX_PAGE_SIZE,
                    cursor=cursor,
                )
                edges.extend(page.edges)
                cursor = page.next_cursor
                if cursor is None:
                    break
        handoff = await self._critiques.read(workspace_id, session_id)
        analyses = dict(snapshot.constraint_analyses)

        items = []
        for artifact in register:
            payload = artifact.payload
            node = nodes_by_artifact.get(artifact.id)
            dependent_ids: dict[UUID, str] = {}
            if node is not None:
                for edge in edges:
                    other_id = None
                    if edge.to_node == node.id and edge.edge_type is not GraphEdgeType.SUPERSEDES:
                        other_id = edge.from_node
                    elif edge.from_node == node.id and edge.edge_type in {
                        GraphEdgeType.CONSTRAINS,
                        GraphEdgeType.QUANTIFIES,
                    }:
                        other_id = edge.to_node
                    other = nodes_by_id.get(other_id) if other_id is not None else None
                    if other is not None and other.kind is not ArtifactKind.CRITIQUE:
                        dependent_ids[other.ref_id] = edge.edge_type.value

            related_claims = set(dependent_ids)
            if isinstance(payload, UncertaintyFields):
                related_claims.add(payload.target_id)
                dependent_ids.setdefault(payload.target_id, GraphEdgeType.QUANTIFIES.value)
            evidence = [
                _artifact_relation(
                    value, nodes_by_artifact.get(value.id), value.payload.relation.value
                )
                for value in snapshot.artifacts
                if isinstance(value.payload, EvidencePayload)
                and value.payload.claim_id in related_claims | {artifact.id}
            ]
            dependents = [
                _artifact_relation(artifacts[value], nodes_by_artifact.get(value), relationship)
                for value, relationship in dependent_ids.items()
                if value in artifacts and artifacts[value].kind is not ArtifactKind.EVIDENCE
            ]
            alternatives = {
                value
                for value in dependent_ids
                if artifacts.get(value) is not None
                and artifacts[value].kind is ArtifactKind.ALTERNATIVE
            }
            dependents.extend(
                {
                    "id": public_id("recommendation", recommendation.id),
                    "kind": "RECOMMENDATION",
                    "relationship": "RECOMMENDS",
                    "label": recommendation.title,
                    "graph_node_id": None,
                    "provenance_href": None,
                }
                for recommendation in snapshot.recommendations
                if recommendation.alternative_id in alternatives
            )
            critiques = []
            for entry in handoff.entries:
                if entry.target_artifact_id != artifact.id or entry.resolution not in {
                    Resolution.OPEN,
                    Resolution.UNRESOLVED,
                    Resolution.DISPUTED,
                }:
                    continue
                critique_node = nodes_by_artifact.get(entry.critique_id)
                critique_artifact = public_id("artifact", entry.critique_id)
                critiques.append(
                    {
                        "id": public_id("critique", entry.critique_id),
                        "artifact_id": critique_artifact,
                        "logical_id": public_id("critique", entry.logical_id),
                        "version": entry.version,
                        "critique_type": entry.critique_type.value,
                        "severity": entry.severity.value,
                        "resolution": entry.resolution,
                        "response_disposition": entry.response_disposition,
                        "graph_node_id": (
                            public_id("graph_node", critique_node.id)
                            if critique_node is not None
                            else None
                        ),
                        "provenance_href": f"/api/v1/artifacts/{critique_artifact}/provenance",
                    }
                )

            representation = None
            context_id = None
            if isinstance(payload, UncertaintyFields):
                dumped = payload.model_dump(mode="json")
                representation = {
                    key: value
                    for key, value in dumped.items()
                    if key not in {"target_id", "uncertainty_type", "drivers"}
                }
                context_id = public_id("artifact", payload.target_id)
            encoded = public_id("artifact", artifact.id)
            items.append(
                {
                    "id": encoded,
                    "logical_id": public_id("artifact", artifact.logical_id),
                    "kind": artifact.kind,
                    "statement": (
                        payload.statement
                        if isinstance(payload, AssumptionPayload | ConstraintPayload)
                        else None
                    ),
                    "basis": payload.basis if isinstance(payload, AssumptionPayload) else None,
                    "materiality": (
                        payload.materiality if isinstance(payload, AssumptionPayload) else None
                    ),
                    "challengeable": (
                        payload.challengeable if isinstance(payload, AssumptionPayload) else None
                    ),
                    "constraint_type": (
                        payload.constraint_type if isinstance(payload, ConstraintPayload) else None
                    ),
                    "category": (
                        payload.category if isinstance(payload, ConstraintPayload) else None
                    ),
                    "formal_status": (
                        payload.formal_status if isinstance(payload, ConstraintPayload) else None
                    ),
                    "uncertainty_type": (
                        payload.uncertainty_type.value
                        if isinstance(payload, UncertaintyFields)
                        else None
                    ),
                    "drivers": payload.drivers if isinstance(payload, UncertaintyFields) else None,
                    "representation": representation,
                    "context_artifact_id": context_id,
                    "owner": {
                        "actor_class": artifact.owner_actor_class,
                        "actor_id": public_id(
                            _actor_resource(artifact.owner_actor_class.value),
                            artifact.owner_actor_id,
                        ),
                    },
                    "round": artifact.round,
                    "version": artifact.version,
                    "lifecycle": artifact.status,
                    "supersedes_id": (
                        public_id("artifact", artifact.supersedes_id)
                        if artifact.supersedes_id
                        else None
                    ),
                    "graph_node_id": public_id("graph_node", node.id) if node is not None else None,
                    "provenance_href": f"/api/v1/artifacts/{encoded}/provenance",
                    "evidence": sorted(
                        evidence, key=lambda value: (value["relationship"], value["id"])
                    ),
                    "dependents": sorted(
                        dependents, key=lambda value: (str(value["kind"]), value["id"])
                    ),
                    "critiques": critiques,
                    "symbolic": (
                        _symbolic(analyses.get(artifact.id))
                        if artifact.kind is ArtifactKind.CONSTRAINT
                        else None
                    ),
                }
            )
        return {
            "data": {"session_id": public_id("session", session_id), "items": items},
            "meta": {
                "request_id": request_id,
                "schema_version": 1,
                "workspace_id": public_id("workspace", workspace_id),
            },
        }
