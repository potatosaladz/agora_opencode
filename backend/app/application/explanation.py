"""Compose a decision explanation exclusively from persisted authorities."""

# ruff: noqa: E501 -- response keys stay adjacent to their persisted source mappings.

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.application.assumption_register import AssumptionRegisterService
from app.application.provenance import ProvenanceService
from app.common.errors import Internal
from app.common.ids import parse_id, public_id
from app.domain.assumption_register import AssumptionRegisterReader
from app.domain.citations import CitationRepository
from app.domain.critique_handoff import CritiqueExplanationHandoffReader
from app.domain.dissent import DissentConsensusExplanationReader
from app.domain.explanation import DecisionExplanationReader, ExplanationEmptyReason
from app.domain.phase3_api import Phase3ArtifactStore
from app.domain.reasoning import (
    AlternativePayload,
    CritiquePayload,
    EvidencePayload,
    EvidenceRelation,
    LifecycleStatus,
    RiskPayload,
    UncertaintyFields,
    Verification,
)
from app.domain.reasoning_graph import ReasoningGraphStore

__all__ = ["DecisionExplanationService"]

_NUMBER_CAVEAT = "Exact persisted strategy value; interpretation is strategy-specific."
_VERIFICATION_ORDER = {
    Verification.REJECTED: 0,
    Verification.DISPUTED: 1,
    Verification.UNVERIFIED: 2,
    Verification.SOURCE_VERIFIED: 3,
    Verification.CROSS_CHECKED: 4,
}


def _number(
    value: Any,
    kind: str,
    version: str,
    caveat: str = _NUMBER_CAVEAT,
    *,
    unit: str = "dimensionless",
) -> dict[str, Any]:
    return {
        "value": str(value),
        "kind": kind,
        "unit": unit,
        "version": version,
        "caveat": caveat,
    }


def _label_numbers(value: Any, *, kind: str, version: str) -> Any:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", value):
        return _number(value, kind, version)
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int | float | Decimal):
        return _number(value, kind, version)
    if isinstance(value, dict):
        return {
            key: _label_numbers(item, kind=f"{kind}.{key}", version=version)
            for key, item in sorted(value.items())
        }
    if isinstance(value, list | tuple):
        return [_label_numbers(item, kind=kind, version=version) for item in value]
    return str(value)


def _artifact_link(
    artifact: Any, label: str | None = None, *, graph_node_id: str | None = None
) -> dict[str, Any]:
    encoded = public_id("artifact", artifact.id)
    payload = artifact.payload
    return {
        "id": encoded,
        "kind": artifact.kind.value,
        "label": label,
        "lifecycle": artifact.status.value,
        "version": _number(
            artifact.version,
            "artifact_revision",
            "reasoning-artifact@1",
            "Immutable persisted artifact revision.",
        ),
        "provenance_href": f"/api/v1/artifacts/{encoded}/provenance",
        "graph_node_id": graph_node_id,
        "content": _public_nested(
            _label_numbers(
                payload.model_dump(mode="python"),
                kind="artifact_payload_value",
                version="reasoning-artifact@1",
            ),
            set(),
        ),
    }


def _public_nested(value: Any, artifacts: set[UUID], key: str = "") -> Any:
    if isinstance(value, UUID):
        resources = {
            "agent_id": "agent",
            "citation_id": "citation",
            "chunk_id": "chunk",
            "document_id": "document",
            "namespace_id": "namespace",
            "source_id": "source",
        }
        return public_id(resources.get(key, "artifact"), value)
    if isinstance(value, dict):
        return {
            item_key: _public_nested(item, artifacts, item_key)
            for item_key, item in sorted(value.items())
        }
    if isinstance(value, list | tuple):
        return [_public_nested(item, artifacts, key.removesuffix("s")) for item in value]
    return value


class DecisionExplanationService:
    def __init__(
        self,
        reader: DecisionExplanationReader,
        explanations: DissentConsensusExplanationReader,
        artifacts: Phase3ArtifactStore,
        graph: ReasoningGraphStore,
        citations: CitationRepository,
        assumption_register: AssumptionRegisterReader,
        critiques: CritiqueExplanationHandoffReader,
    ) -> None:
        self._reader = reader
        self._explanations = explanations
        self._artifacts = artifacts
        self._graph = graph
        self._citations = citations
        self._assumption_register = assumption_register
        self._critiques = critiques

    # trace: FR-504, FR-505, FR-605, FR-609, FR-804, FR-805, FR-901, NFR-005, NFR-019
    async def read(
        self, workspace_id: UUID, session_id: UUID, *, request_id: str
    ) -> dict[str, Any]:
        snapshot = await self._reader.read(workspace_id, session_id)
        latest = snapshot.latest_consensus
        explanation = (
            await self._explanations.get(workspace_id, latest.id) if latest is not None else None
        )
        assumptions = await AssumptionRegisterService(
            self._assumption_register, self._graph, self._critiques
        ).read(workspace_id, session_id, request_id=request_id)
        handoff = await self._critiques.read(workspace_id, session_id)
        artifact_by_id = {artifact.id: artifact for artifact in snapshot.artifacts}
        graph_nodes = {node.ref_id: node for node in snapshot.graph_nodes}

        def artifact_link(artifact: Any, label: str | None = None) -> dict[str, Any]:
            node = graph_nodes.get(artifact.id)
            return _artifact_link(
                artifact,
                label,
                graph_node_id=(public_id("graph_node", node.id) if node is not None else None),
            )

        version = latest.strategy_version if latest is not None else "unavailable"
        links = {
            "graph": (
                f"#/graph?root={public_id('graph_node', graph_nodes[latest.selected_alternative_id].id)}"
                if latest is not None
                and latest.selected_alternative_id is not None
                and latest.selected_alternative_id in graph_nodes
                else "#/graph"
            ),
            "dissent": "#/dissent",
            "assumptions": "#/assumptions",
            "provenance": (
                f"/api/v1/artifacts/{public_id('artifact', latest.selected_alternative_id)}/provenance"
                if latest is not None and latest.selected_alternative_id is not None
                else ""
            ),
        }
        empty_reason = None
        if latest is None:
            empty_reason = ExplanationEmptyReason.NO_CONSENSUS_RESULT
        elif explanation is None:
            empty_reason = ExplanationEmptyReason.EXPLANATION_UNAVAILABLE
        if empty_reason is not None:
            reason = (
                "No persisted consensus result exists."
                if latest is None
                else "The latest persisted consensus result has no persisted explanation."
            )
            critiques = [
                await self._critique(workspace_id, session_id, entry) for entry in handoff.entries
            ]
            risks = [
                artifact_link(artifact)
                for artifact in snapshot.artifacts
                if isinstance(artifact.payload, RiskPayload | UncertaintyFields)
            ]
            return self._empty(
                workspace_id,
                session_id,
                request_id,
                empty_reason,
                reason,
                assumptions["data"],
                handoff,
                links,
                critiques,
                risks,
            )
        assert latest is not None
        assert explanation is not None

        selected = (
            artifact_by_id.get(latest.selected_alternative_id)
            if latest.selected_alternative_id is not None
            else None
        )
        if latest.selected_alternative_id is not None and selected is None:
            raise Internal("persisted selected alternative is missing")
        provenance = None
        if latest.selected_alternative_id is not None:
            provenance = await ProvenanceService(
                self._artifacts, self._graph, self._citations
            ).provenance_of(workspace_id, latest.selected_alternative_id)

        evidence: dict[str, list[dict[str, Any]]] = {
            "supporting": [],
            "opposing": [],
            "qualifying": [],
        }
        provenance_ids = (
            {node.graph_node.ref_id for node in provenance.nodes}
            if provenance is not None
            else set()
        )
        for artifact in snapshot.artifacts:
            if not isinstance(artifact.payload, EvidencePayload):
                continue
            if (
                artifact.id not in provenance_ids
                and artifact.payload.claim_id != latest.selected_alternative_id
            ):
                continue
            citations = await self._citations.citations_for_evidence(workspace_id, artifact.id)
            rendered = artifact_link(artifact)
            rendered["relation"] = artifact.payload.relation.value
            rendered["quote"] = artifact.payload.quote
            rendered["verification"] = artifact.payload.verification.value
            rendered["trust_level"] = artifact.payload.trust_level.value
            rendered["provenance_kind"] = artifact.payload.provenance_kind.value
            rendered["weight"] = _number(
                artifact.payload.weight,
                "evidence_weight",
                "reasoning-artifact@1",
                "Persisted evidentiary weight; not confidence or probability.",
            )
            rendered["citations"] = [
                _public_nested(
                    _label_numbers(
                        item.model_dump(mode="python"),
                        kind="citation_value",
                        version="citation-resolution@1",
                    ),
                    set(),
                )
                for item in citations
            ]
            key = {
                EvidenceRelation.SUPPORTS: "supporting",
                EvidenceRelation.OPPOSES: "opposing",
                EvidenceRelation.QUALIFIES: "qualifying",
            }[artifact.payload.relation]
            evidence[key].append(rendered)
        for values in evidence.values():
            values.sort(key=lambda item: item["id"])

        alternative_ids = {
            artifact.id
            for artifact in snapshot.artifacts
            if isinstance(artifact.payload, AlternativePayload)
        }
        alternative_ids.update(latest.pareto_set)
        if latest.selected_alternative_id is not None:
            alternative_ids.add(latest.selected_alternative_id)
        alternative_ids.update(item.alternative_id for item in explanation.contributions)
        alternatives = [
            {
                **artifact_link(artifact_by_id[value]),
                "selected": value == latest.selected_alternative_id,
                "pareto": value in latest.pareto_set,
            }
            for value in sorted(alternative_ids, key=lambda item: item.int)
            if value in artifact_by_id
        ]

        recommendations = [
            {
                "id": public_id("recommendation", item.id),
                "alternative_id": (
                    public_id("artifact", item.alternative_id)
                    if item.alternative_id is not None
                    else None
                ),
                "rank": _number(item.rank, "recommendation_rank", "recommendation@1"),
                "title": item.title,
                "statement": item.statement,
                "conditions": _label_numbers(
                    item.conditions, kind="condition", version="recommendation@1"
                ),
                "risk_ids": [public_id("artifact", value) for value in item.risk_ids],
                "open_questions": _label_numbers(
                    item.open_questions, kind="open_question", version="recommendation@1"
                ),
                "is_override": item.is_override,
                "override_by": public_id("user", item.override_by) if item.override_by else None,
                "override_reason": item.override_reason,
            }
            for item in snapshot.recommendations
        ]
        critiques = [
            await self._critique(workspace_id, session_id, entry) for entry in handoff.entries
        ]
        unresolved = [
            item for item in critiques if item["resolution"] in {"OPEN", "UNRESOLVED", "DISPUTED"}
        ]
        risks = [
            artifact_link(artifact)
            for artifact in snapshot.artifacts
            if isinstance(artifact.payload, RiskPayload | UncertaintyFields)
        ]
        symbolic = [
            {"constraint_id": item["id"], **item["symbolic"]}
            for item in assumptions["data"]["items"]
            if item["kind"] == "CONSTRAINT" and item["symbolic"] is not None
        ]
        minority = [
            {
                "agent_id": public_id("agent", item.agent_id),
                "position": item.position,
                "warrant_artifact_ids": [
                    public_id("artifact", value) for value in item.warrant_artifact_ids
                ],
                "disputed_proposition_ids": [
                    public_id("proposition", value) for value in item.disputed_propositions
                ],
                "unresolved_critique_ids": [
                    public_id("critique", value) for value in item.unresolved_critiques
                ],
                "what_would_change": item.what_would_change or None,
            }
            for item in explanation.minority_report
        ]
        weakest = self._weakest(evidence, explanation.caveats)
        if weakest["available"] is True:
            weakest_artifact = artifact_by_id.get(parse_id("artifact", str(weakest["evidence_id"])))
            if weakest_artifact is not None:
                weakest.update(artifact_link(weakest_artifact))
        supporting_drivers = [
            {"artifact_id": item["id"], "relationship": "SUPPORTS"}
            for item in evidence["supporting"]
        ]
        inhibitors = [
            {"artifact_id": item["id"], "relationship": item["relation"]}
            for key in ("opposing", "qualifying")
            for item in evidence[key]
        ]
        inhibitors.extend(
            {
                "critique_id": item["id"],
                "relationship": "UNRESOLVED_CRITIQUE",
                "resolution": item["resolution"],
            }
            for item in unresolved
        )
        absent = [
            item
            for recommendation in snapshot.recommendations
            for item in recommendation.open_questions
        ]
        artifact_ids = set(artifact_by_id)
        return {
            "data": {
                "session_id": public_id("session", session_id),
                "status": "AVAILABLE",
                "empty_reason": None,
                "decision": {
                    "empty_reason": None,
                    "consensus_result_id": public_id("consensus_result", latest.id),
                    "round": _number(latest.round, "consensus_round", version),
                    "outcome": latest.outcome.value,
                    "selected_alternative_id": public_id("artifact", latest.selected_alternative_id)
                    if latest.selected_alternative_id
                    else None,
                    "pareto_alternative_ids": [
                        public_id("artifact", value) for value in latest.pareto_set
                    ],
                    "persisted_measures": {
                        "support": (
                            _number(
                                latest.support,
                                "consensus_support",
                                version,
                                "Persisted strategy support; not confidence or probability.",
                            )
                            if latest.support is not None
                            else None
                        ),
                        "dissent": (
                            _number(latest.dissent, "consensus_dissent_ratio", version)
                            if latest.dissent is not None
                            else None
                        ),
                        "abstention": (
                            _number(latest.abstention, "consensus_abstention_ratio", version)
                            if latest.abstention is not None
                            else None
                        ),
                        "coverage": (
                            _number(latest.coverage, "consensus_coverage_ratio", version)
                            if latest.coverage is not None
                            else None
                        ),
                    },
                    "constraint_report": _label_numbers(
                        latest.constraint_report,
                        kind="constraint_report_value",
                        version=version,
                    ),
                },
                "recommendation": {
                    "empty_reason": None if recommendations else "NO_PERSISTED_RECOMMENDATION",
                    "items": recommendations,
                },
                "why": {
                    "empty_reason": None,
                    "formula": explanation.formula,
                    "strategy": explanation.strategy,
                    "strategy_version": explanation.strategy_version,
                    "weights": _label_numbers(
                        explanation.weights, kind="strategy_weight", version=version
                    ),
                    "thresholds": _label_numbers(
                        explanation.thresholds, kind="strategy_threshold", version=version
                    ),
                    "derivation": _label_numbers(
                        _public_nested(
                            [item.model_dump(mode="python") for item in explanation.derivation],
                            artifact_ids,
                        ),
                        kind="derivation_value",
                        version=version,
                    ),
                    "contributions": [
                        {
                            "agent_id": public_id("agent", item.agent_id),
                            "alternative_id": public_id("artifact", item.alternative_id),
                            "stance": item.stance,
                            "position_score": _number(
                                item.position_score, "position_score", version
                            ),
                            "agent_reported_confidence": _number(
                                item.confidence,
                                "agent_reported_confidence",
                                version,
                                "Persisted agent self-report; not consensus support or probability.",
                            ),
                            "evidence_score": _number(
                                item.evidence_score,
                                "evidence_score",
                                version,
                                "Persisted strategy evidence value; not confidence or probability.",
                            ),
                        }
                        for item in explanation.contributions
                    ],
                    "caveats": list(explanation.caveats),
                    "drivers": {
                        "empty_reason": None
                        if supporting_drivers
                        else "NO_PERSISTED_SUPPORTING_DRIVERS",
                        "items": supporting_drivers,
                    },
                    "inhibitors": {
                        "empty_reason": None if inhibitors else "NO_PERSISTED_INHIBITORS",
                        "items": inhibitors,
                    },
                    "absent": {
                        "empty_reason": None
                        if absent
                        else "NO_PERSISTED_ABSENT_EVIDENCE_OR_OPEN_QUESTIONS",
                        "items": _label_numbers(
                            absent, kind="absent_evidence", version="recommendation@1"
                        ),
                    },
                },
                "alternatives": alternatives,
                "evidence": evidence,
                "assumptions_constraints": {
                    "empty_reason": None
                    if assumptions["data"]["items"]
                    else "NO_PERSISTED_REGISTER_ITEMS",
                    "items": _label_numbers(
                        assumptions["data"]["items"],
                        kind="assumption_register_value",
                        version="assumption-register@1",
                    ),
                },
                "minority": minority,
                "critiques": {
                    "empty_reason": handoff.empty_reason.value if handoff.empty_reason else None,
                    "all": critiques,
                    "unresolved": unresolved,
                },
                "risks_uncertainties": {
                    "empty_reason": None if risks else "NO_PERSISTED_RISKS_OR_UNCERTAINTIES",
                    "items": risks,
                },
                "symbolic_feasibility": {
                    "empty_reason": None if symbolic else "NO_CONSTRAINT_ANALYSIS",
                    "constraints": symbolic,
                },
                "conditions_counterfactuals": {
                    "empty_reason": None
                    if latest.conditions or explanation.counterfactuals
                    else "NO_PERSISTED_CONDITIONS_OR_COUNTERFACTUALS",
                    "conditions": _label_numbers(
                        latest.conditions, kind="condition", version=version
                    ),
                    "counterfactuals": _label_numbers(
                        [item.model_dump(mode="python") for item in explanation.counterfactuals],
                        kind="counterfactual_value",
                        version=version,
                    ),
                },
                "weakest_evidence": weakest,
                "provenance": {
                    "empty_reason": None
                    if provenance
                    else "SELECTED_ALTERNATIVE_PROVENANCE_UNAVAILABLE",
                    "complete": provenance is not None
                    and not provenance.truncated
                    and provenance.next_cursor is None,
                    "truncated": provenance.truncated if provenance else False,
                    "next_cursor": provenance.next_cursor if provenance else None,
                    "href": links["provenance"] or None,
                },
                "links": links,
            },
            "meta": {
                "request_id": request_id,
                "schema_version": 1,
                "workspace_id": public_id("workspace", workspace_id),
            },
        }

    async def _critique(self, workspace_id: UUID, session_id: UUID, entry: Any) -> dict[str, Any]:
        artifact = await self._artifacts.get(workspace_id, entry.critique_id, session_id=session_id)
        argument = (
            artifact.payload.argument
            if artifact and isinstance(artifact.payload, CritiquePayload)
            else None
        )
        encoded = public_id("artifact", entry.critique_id)
        return {
            "id": public_id("critique", entry.critique_id),
            "artifact_id": encoded,
            "logical_id": public_id("critique", entry.logical_id),
            "version": _number(entry.version, "critique_revision", "critique@1"),
            "creation_ledger_seq": _number(
                entry.creation_ledger_seq,
                "critique_creation_ledger_sequence",
                "reasoning-ledger@1",
                "Persisted per-session ledger order.",
            ),
            "target_artifact_id": public_id("artifact", entry.target_artifact_id),
            "critique_type": entry.critique_type.value,
            "severity": entry.severity.value,
            "resolution": entry.resolution.value,
            "response_disposition": entry.response_disposition.value
            if entry.response_disposition
            else None,
            "warrant_artifact_ids": [
                public_id("artifact", value) for value in entry.warrant_artifact_ids
            ],
            "replacement_target_artifact_id": public_id(
                "artifact", entry.replacement_target_artifact_id
            )
            if entry.replacement_target_artifact_id
            else None,
            "argument": argument,
            "provenance_href": f"/api/v1/artifacts/{encoded}/provenance",
        }

    @staticmethod
    def _weakest(
        evidence: dict[str, list[dict[str, Any]]], caveats: tuple[str, ...]
    ) -> dict[str, Any]:
        candidates = [item for values in evidence.values() for item in values]
        if not candidates:
            return {
                "available": False,
                "evidence_id": None,
                "rationale": "Unavailable: no persisted evidence is present in selected-alternative provenance.",
            }

        def key(item: dict[str, Any]) -> tuple[int, int, int, int, str]:
            return (
                _VERIFICATION_ORDER[Verification(item["verification"])],
                0 if item["lifecycle"] != LifecycleStatus.ACTIVE.value else 1,
                0 if not item["citations"] else 1,
                0 if item["relation"] == EvidenceRelation.OPPOSES.value else 1,
                item["id"],
            )

        weakest = min(candidates, key=key)
        reasons = [
            f"verification={weakest['verification']}",
            f"lifecycle={weakest['lifecycle']}",
            f"citations={'present' if weakest['citations'] else 'missing'}",
            f"relation={weakest['relation']}",
        ]
        if caveats:
            reasons.append("consensus explanation records caveats")
        return {
            "available": True,
            "evidence_id": weakest["id"],
            "rationale": "; ".join(reasons)
            + ". Deterministic order: verification, lifecycle, citation presence, opposing relation, public id.",
        }

    @staticmethod
    def _empty(
        workspace_id: UUID,
        session_id: UUID,
        request_id: str,
        empty_reason: ExplanationEmptyReason,
        reason: str,
        assumptions: dict[str, Any],
        handoff: Any,
        links: dict[str, str],
        critiques: list[dict[str, Any]],
        risks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        unavailable = {"empty_reason": empty_reason.value, "reason": reason}
        return {
            "data": {
                "session_id": public_id("session", session_id),
                "status": empty_reason.value,
                "empty_reason": empty_reason,
                "decision": unavailable,
                "recommendation": {**unavailable, "items": []},
                "why": {
                    **unavailable,
                    "formula": None,
                    "strategy": None,
                    "strategy_version": None,
                    "derivation": [],
                    "contributions": [],
                    "caveats": [],
                    "drivers": {"empty_reason": empty_reason.value, "items": []},
                    "inhibitors": {"empty_reason": empty_reason.value, "items": []},
                    "absent": {"empty_reason": empty_reason.value, "items": []},
                },
                "alternatives": [],
                "evidence": {"supporting": [], "opposing": [], "qualifying": []},
                "assumptions_constraints": {
                    "empty_reason": None if assumptions["items"] else "NO_PERSISTED_REGISTER_ITEMS",
                    "items": _label_numbers(
                        assumptions["items"],
                        kind="assumption_register_value",
                        version="assumption-register@1",
                    ),
                },
                "minority": [],
                "critiques": {
                    "empty_reason": handoff.empty_reason.value if handoff.empty_reason else None,
                    "all": critiques,
                    "unresolved": [
                        item
                        for item in critiques
                        if item["resolution"] in {"OPEN", "UNRESOLVED", "DISPUTED"}
                    ],
                },
                "risks_uncertainties": {
                    "empty_reason": None if risks else "NO_PERSISTED_RISKS_OR_UNCERTAINTIES",
                    "items": risks,
                },
                "symbolic_feasibility": {"empty_reason": empty_reason.value, "constraints": []},
                "conditions_counterfactuals": {
                    "empty_reason": empty_reason.value,
                    "conditions": [],
                    "counterfactuals": [],
                },
                "weakest_evidence": {
                    "available": False,
                    "evidence_id": None,
                    "rationale": "Unavailable because no persisted consensus explanation can be evaluated.",
                },
                "provenance": {
                    "empty_reason": empty_reason.value,
                    "complete": False,
                    "truncated": False,
                    "next_cursor": None,
                    "href": None,
                },
                "links": links,
            },
            "meta": {
                "request_id": request_id,
                "schema_version": 1,
                "workspace_id": public_id("workspace", workspace_id),
            },
        }
