"""Authenticated exposure of the eight existing Phase 13 audit queries."""

from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from app.api.audit_contracts import (
    AuditCompleteness,
    AuditIntegrity,
    AuditQueryRequest,
    AuditQuestion,
    AuditResponse,
    Q1Request,
    Q2Request,
    Q3Request,
    Q4Request,
    Q5Request,
    Q6Request,
    Q7Request,
)
from app.api.errors import not_found
from app.application.audit import AccessAuditService, AuditQueryService, ChainVerificationService
from app.application.provenance import ProvenanceService
from app.common.errors import ValidationFailed
from app.common.ids import parse_id, public_id
from app.domain.audit import AccessLogEntry, AccessResult, AuditResourceKind
from app.domain.reasoning import ActorClass
from app.domain.session_lifecycle import TERMINAL_SESSION_STATES
from app.ports.auth import WorkspaceRole
from app.security import current_principal, require_roles, require_scopes

router = APIRouter(prefix="/api/v1/sessions", tags=["audit"])
_AUDIT_READ = tuple(WorkspaceRole)
_QUESTIONS = {
    AuditQuestion.Q1: "Why is this claim in the record?",
    AuditQuestion.Q2: "Who changed this epistemic status, and on what warrant?",
    AuditQuestion.Q3: "What did the agents see at round n?",
    AuditQuestion.Q4: "Was a dissent suppressed?",
    AuditQuestion.Q5: "Why did the session end?",
    AuditQuestion.Q6: "Which strategy and parameters produced this ranking?",
    AuditQuestion.Q7: "Who accessed this recommendation before it was accepted?",
    AuditQuestion.Q8: "Has anything been altered since it was written?",
}


def _parse(resource: str, value: str, field: str) -> UUID:
    try:
        return parse_id(resource, value)
    except ValueError as exc:
        raise ValidationFailed(f"{field} contains a malformed public identifier") from exc


def _actor_id(actor_class: ActorClass, actor_id: UUID) -> str:
    resource = {
        ActorClass.HUMAN: "user",
        ActorClass.AGENT: "agent",
        ActorClass.SERVICE: "service",
        ActorClass.POLICY: "policy",
    }[actor_class]
    return public_id(resource, actor_id)


def _event(value: Any) -> dict[str, Any]:
    return {
        "event_id": public_id("event", value.id),
        "event_type": value.event_type,
        "ledger_seq": value.ledger_seq,
        "round": value.round,
        "actor_class": value.actor_class.value,
        "actor_id": _actor_id(value.actor_class, value.actor_id),
        "recorded_at": value.recorded_at.isoformat(),
        "event_hash": value.event_hash,
    }


def _provenance(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "root_artifact_id": public_id("artifact", value.root_artifact_id),
        "root_artifact_version": value.root_artifact_version,
        "root_node_id": public_id("graph_node", value.root_node.id),
        "nodes": [
            {
                "graph_node_id": public_id("graph_node", item.graph_node.id),
                "artifact_id": public_id("artifact", item.graph_node.ref_id),
                "kind": item.graph_node.kind.value,
                "label": item.graph_node.label,
                "artifact_version": item.artifact_version,
                "verification": item.verification.value if item.verification else None,
                "citations": [
                    {
                        "citation_id": public_id("citation", citation.citation.citation_id),
                        "source_id": public_id("source", citation.citation.snapshot.source_id),
                        "document_id": public_id(
                            "document", citation.citation.snapshot.document_id
                        ),
                        "chunk_id": public_id("chunk", citation.citation.snapshot.chunk_id),
                        "citation": citation.citation.snapshot.citation,
                        "source_status": citation.current_source_status.value,
                    }
                    for citation in item.citations
                ],
            }
            for item in value.nodes
        ],
        "edges": [
            {
                "edge_id": public_id("graph_edge", edge.id),
                "from_node": public_id("graph_node", edge.from_node),
                "to_node": public_id("graph_node", edge.to_node),
                "edge_type": edge.edge_type.value,
            }
            for edge in value.edges
        ],
        "truncated": value.truncated,
        "next_cursor": value.next_cursor,
    }


def _state(
    completeness: AuditCompleteness,
    *,
    completeness_reasons: tuple[str, ...] = (),
    integrity: AuditIntegrity = AuditIntegrity.NOT_APPLICABLE,
    integrity_reasons: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "completeness": completeness,
        "completeness_reasons": completeness_reasons,
        "integrity": integrity,
        "integrity_reasons": integrity_reasons,
    }


def _links() -> dict[str, str]:
    return {
        "session": "#/",
        "graph": "#/graph",
        "dissent": "#/dissent",
        "assumptions": "#/assumptions",
        "explanation": "#/explanation",
        "replay": "#/replay",
    }


async def _answer(
    tx: Any,
    workspace_id: UUID,
    session_id: UUID,
    body: AuditQueryRequest,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], dict[str, Any], dict[str, Any]]:
    query = AuditQueryService(
        tx.artifacts,
        tx.consensus_results,
        tx.lifecycle,
        tx.session_participants,
        ProvenanceService(tx.artifacts, tx.graph, tx.citations),
        tx.ledger,
        tx.dissent_explanations,
    )
    parameters: dict[str, Any] = {"session_id": public_id("session", session_id)}
    pagination: dict[str, Any] = {"truncated": False, "next_cursor": None}

    if isinstance(body, Q1Request):
        artifact_id = _parse("artifact", body.artifact_id, "artifact_id")
        parameters.update(
            artifact_id=body.artifact_id,
            max_depth=body.max_depth,
            limit=body.limit,
            cursor=body.cursor,
        )
        try:
            rationale = await query.artifact_rationale(
                workspace_id,
                artifact_id,
                max_depth=body.max_depth,
                page_size=body.limit,
                cursor=body.cursor,
            )
        except ValueError as exc:
            raise ValidationFailed("cursor is malformed") from exc
        if rationale is None or rationale.session_id != session_id:
            raise not_found("artifact")
        provenance = _provenance(rationale.provenance)
        reasons = tuple(
            reason
            for reason, missing in (
                ("PROVENANCE_UNAVAILABLE", provenance is None),
                ("COMMIT_EVENT_UNAVAILABLE", rationale.committed_by_event is None),
                ("ORIGINATING_TURN_UNAVAILABLE", rationale.originating_turn_event is None),
            )
            if missing
        )
        if provenance and provenance["truncated"]:
            reasons += ("PROVENANCE_TRUNCATED",)
        pagination = {
            "truncated": bool(provenance and provenance["truncated"]),
            "next_cursor": provenance["next_cursor"] if provenance else None,
        }
        rationale_answer: dict[str, Any] = {
            "kind": "ARTIFACT_RATIONALE",
            "artifact_id": body.artifact_id,
            "provenance": provenance,
            "committed_by_event": (
                _event(rationale.committed_by_event) if rationale.committed_by_event else None
            ),
            "originating_turn_event": (
                _event(rationale.originating_turn_event)
                if rationale.originating_turn_event
                else None
            ),
        }
        evidence = tuple(
            item
            for item in (
                rationale_answer["committed_by_event"],
                rationale_answer["originating_turn_event"],
            )
            if isinstance(item, dict)
        )
        return (
            rationale_answer,
            evidence,
            _state(
                AuditCompleteness.INCOMPLETE if reasons else AuditCompleteness.COMPLETE,
                completeness_reasons=reasons,
            ),
            pagination,
        )

    if isinstance(body, Q2Request):
        artifact_id = _parse("artifact", body.artifact_id, "artifact_id")
        if await tx.artifacts.get(workspace_id, artifact_id, session_id=session_id) is None:
            raise not_found("artifact")
        parameters["artifact_id"] = body.artifact_id
        history = await query.artifact_revision_history(workspace_id, session_id, artifact_id)
        revisions = tuple(
            {
                "event_id": public_id("event", item.event_id),
                "version": item.version,
                "ledger_seq": item.ledger_seq,
                "round": item.round,
                "event_type": item.event_type,
                "actor_class": item.actor_class.value,
                "actor_id": _actor_id(item.actor_class, item.actor_id),
                "recorded_at": item.recorded_at.isoformat(),
                "supersedes_id": (
                    public_id("artifact", item.supersedes_id) if item.supersedes_id else None
                ),
                "warrant_artifact_ids": [
                    public_id("artifact", warrant) for warrant in item.warrant_artifact_ids
                ],
            }
            for item in history.revisions
        )
        reasons = () if revisions else ("NO_RECORDED_REVISION_WRITES",)
        return (
            {
                "kind": "ARTIFACT_REVISION_HISTORY",
                "artifact_id": body.artifact_id,
                "revisions": revisions,
            },
            revisions,
            _state(
                AuditCompleteness.COMPLETE if revisions else AuditCompleteness.INCOMPLETE,
                completeness_reasons=reasons,
            ),
            pagination,
        )

    if isinstance(body, Q3Request):
        parameters["round"] = body.round
        context = await query.round_participant_context(workspace_id, session_id, round=body.round)
        if context is None:
            raise not_found("session")
        participants = tuple(
            {
                "agent_id": public_id("agent", item.agent_definition_id),
                "name": item.name,
                "domain": item.domain,
                "role": item.role_kind.value,
            }
            for item in context.participants
        )
        turns = tuple(_event(item) for item in context.turn_events)
        reasons = () if turns else ("NO_COMPLETED_AGENT_TURNS_FOR_ROUND",)
        return (
            {
                "kind": "ROUND_CONTEXT",
                "round": context.round,
                "participants": participants,
                "turn_events": turns,
            },
            turns,
            _state(
                AuditCompleteness.COMPLETE if turns else AuditCompleteness.INCOMPLETE,
                completeness_reasons=reasons,
            ),
            pagination,
        )

    if isinstance(body, Q4Request):
        parameters["round"] = body.round
        consensus_bundle = await query.round_consensus_explanation(
            workspace_id, session_id, round=body.round
        )
        if consensus_bundle is None:
            return (
                {
                    "kind": "DISSENT_SUPPRESSION_CHECK",
                    "consensus_result_id": None,
                    "outcome": None,
                    "all_persisted_positions_included": False,
                    "contributions": (),
                    "minority_report": (),
                },
                (),
                _state(
                    AuditCompleteness.NOT_APPLICABLE,
                    completeness_reasons=("NO_CONSENSUS_RESULT_FOR_ROUND",),
                ),
                pagination,
            )
        consensus, explanation = consensus_bundle
        contributions = (
            tuple(
                {
                    "agent_id": public_id("agent", item.agent_id),
                    "alternative_id": public_id("artifact", item.alternative_id),
                    "stance": item.stance,
                    "position_score": str(item.position_score),
                    "confidence": str(item.confidence),
                    "evidence_score": str(item.evidence_score),
                }
                for item in explanation.contributions
            )
            if explanation
            else ()
        )
        minority = (
            tuple(
                {
                    "agent_id": public_id("agent", item.agent_id),
                    "position": item.position,
                    "warrant_artifact_ids": [
                        public_id("artifact", warrant) for warrant in item.warrant_artifact_ids
                    ],
                    "what_would_change": item.what_would_change,
                }
                for item in explanation.minority_report
            )
            if explanation
            else ()
        )
        reasons = () if explanation else ("CONSENSUS_EXPLANATION_UNAVAILABLE",)
        dissent_answer: dict[str, Any] = {
            "kind": "DISSENT_SUPPRESSION_CHECK",
            "consensus_result_id": public_id("consensus_result", consensus.id),
            "outcome": consensus.outcome.value,
            "all_persisted_positions_included": explanation is not None,
            "contributions": contributions,
            "minority_report": minority,
        }
        return (
            dissent_answer,
            contributions + minority,
            _state(
                AuditCompleteness.COMPLETE if explanation else AuditCompleteness.INCOMPLETE,
                completeness_reasons=reasons,
            ),
            pagination,
        )

    if isinstance(body, Q5Request):
        termination = await query.session_termination(workspace_id, session_id)
        if termination is None:
            raise not_found("session")
        terminal = termination.final_state in TERMINAL_SESSION_STATES
        termination_answer: dict[str, Any] = {
            "kind": "SESSION_TERMINATION",
            "final_state": termination.final_state.value if termination.final_state else None,
            "final_round": termination.final_round,
            "ended_at": termination.ended_at.isoformat() if termination.ended_at else None,
            "last_event": _event(termination.last_event) if termination.last_event else None,
        }
        last_event = termination_answer["last_event"]
        evidence = (last_event,) if isinstance(last_event, dict) else ()
        return (
            termination_answer,
            evidence,
            _state(
                AuditCompleteness.COMPLETE if terminal else AuditCompleteness.NOT_APPLICABLE,
                completeness_reasons=() if terminal else ("SESSION_NOT_TERMINAL",),
            ),
            pagination,
        )

    if isinstance(body, Q6Request):
        parameters["round"] = body.round
        usage = await query.strategy_usage(workspace_id, session_id, round=body.round)
        if usage is None:
            return (
                {"kind": "STRATEGY_USAGE", "strategy": None},
                (),
                _state(
                    AuditCompleteness.NOT_APPLICABLE,
                    completeness_reasons=("NO_CONSENSUS_RESULT_FOR_ROUND",),
                ),
                pagination,
            )
        consensus_bundle = await query.round_consensus_explanation(
            workspace_id, session_id, round=body.round
        )
        explanation = consensus_bundle[1] if consensus_bundle else None
        reasons = () if explanation else ("STRATEGY_PARAMETERS_UNAVAILABLE",)
        usage_answer: dict[str, Any] = {
            "kind": "STRATEGY_USAGE",
            "strategy": usage.strategy,
            "strategy_version": usage.strategy_version,
            "input_hash": usage.input_hash,
            "outcome": usage.outcome.value,
            "conditions": usage.conditions,
            "pareto_set": [public_id("artifact", item) for item in usage.pareto_set],
            "created_at": usage.created_at.isoformat(),
            "formula": explanation.formula if explanation else None,
            "weights": explanation.weights if explanation else {},
            "thresholds": explanation.thresholds if explanation else {},
        }
        return (
            usage_answer,
            (usage_answer,),
            _state(
                AuditCompleteness.COMPLETE if explanation else AuditCompleteness.INCOMPLETE,
                completeness_reasons=reasons,
            ),
            pagination,
        )

    if isinstance(body, Q7Request):
        recommendation_id = _parse("recommendation", body.recommendation_id, "recommendation_id")
        parameters.update(
            recommendation_id=body.recommendation_id,
            limit=body.limit,
            cursor=body.cursor,
        )
        try:
            access_report = await AccessAuditService(tx.access_logs).recommendation_access(
                workspace_id,
                recommendation_id,
                session_id=session_id,
                limit=body.limit,
                cursor=body.cursor,
            )
        except ValueError as exc:
            raise ValidationFailed("cursor is malformed") from exc
        if not access_report.recommendation_known:
            raise not_found("recommendation")
        entries = tuple(
            {
                "principal_class": item.principal_class.value,
                "principal_id": _actor_id(item.principal_class, item.principal_id),
                "action": item.action.value,
                "result": item.result.value,
                "scope_ids": item.scope_ids,
                "recorded_at": item.recorded_at.isoformat(),
            }
            for item in access_report.entries
        )
        reasons = (
            ()
            if access_report.complete_timeline
            else (access_report.why_incomplete or "PAGINATED_ACCESS_HISTORY",)
        )
        pagination = {
            "truncated": access_report.truncated,
            "next_cursor": access_report.next_cursor,
        }
        return (
            {
                "kind": "RECOMMENDATION_ACCESS",
                "recommendation_id": body.recommendation_id,
                "recommendation_created_at": access_report.recommendation_created_at.isoformat()
                if access_report.recommendation_created_at
                else None,
                "boundary": "STRICTLY_BEFORE_RECOMMENDATION_CREATED_AT",
                "entries": entries,
            },
            entries,
            _state(
                AuditCompleteness.COMPLETE
                if access_report.complete_timeline
                else AuditCompleteness.INCOMPLETE,
                completeness_reasons=reasons,
            ),
            pagination,
        )

    report = await ChainVerificationService(tx.audit_anchors, tx.ledger).chain_integrity(
        workspace_id, session_id
    )
    anchors = tuple(
        {
            "anchor_day": item.anchor.anchor_day.isoformat(),
            "head_seq": item.anchor.head_seq,
            "head_hash": item.anchor.head_hash,
            "prev_head_hash": item.anchor.prev_head_hash,
            "anchor_hash": item.anchor.anchor_hash,
            "anchored_at": item.anchor.anchored_at.isoformat(),
            "valid": item.valid,
            "reason": item.reason,
        }
        for item in report.anchors
    )
    if not report.chain_valid:
        integrity = AuditIntegrity.ALTERED
        integrity_reasons = tuple(
            reason
            for reason in (
                report.ledger_verification.reason,
                *(item.reason for item in report.anchors if not item.valid),
            )
            if reason
        )
    elif not anchors:
        integrity = AuditIntegrity.NOT_VERIFIABLE
        integrity_reasons = ("NO_PUBLISHED_ANCHORS",)
    else:
        integrity = AuditIntegrity.VERIFIED_UNALTERED
        integrity_reasons = ()
    chain_answer: dict[str, Any] = {
        "kind": "CHAIN_VERIFICATION",
        "event_count": report.event_count,
        "ledger_valid": report.ledger_verification.valid,
        "ledger_reason": report.ledger_verification.reason,
        "ledger_head_hash": report.ledger_verification.head_hash,
        "chain_valid": report.chain_valid if anchors else None,
        "first_invalid_day": (
            report.first_invalid_day.isoformat() if report.first_invalid_day else None
        ),
        "anchors": anchors,
    }
    return (
        chain_answer,
        anchors,
        _state(
            AuditCompleteness.COMPLETE if anchors else AuditCompleteness.INCOMPLETE,
            completeness_reasons=() if anchors else ("NO_PUBLISHED_ANCHORS",),
            integrity=integrity,
            integrity_reasons=integrity_reasons,
        ),
        pagination,
    )


@router.post("/{session_id}/audit/query")
@require_roles(*_AUDIT_READ)
@require_scopes("audit:read")
# trace: FR-802, FR-807, NFR-006, NFR-010, NFR-019
async def query_session_audit(
    request: Request, session_id: str, body: AuditQueryRequest
) -> JSONResponse:
    """Delegate one of Q1..Q8 and append the audit read in the same transaction."""
    principal = current_principal(request)
    try:
        internal_session_id = parse_id("session", session_id)
    except ValueError as exc:
        raise not_found("session") from exc
    async with request.app.state.container.reasoning_transaction(principal.workspace_id) as tx:
        if await tx.sessions.get(principal.workspace_id, internal_session_id) is None:
            raise not_found("session")
        try:
            answer, evidence, state, pagination = await _answer(
                tx, principal.workspace_id, internal_session_id, body
            )
        except ValidationError as exc:
            raise ValidationFailed(str(exc)) from exc
        client_host = request.client.host if request.client is not None else None
        try:
            source_ip = ip_address(client_host) if client_host else None
        except ValueError:
            source_ip = None
        await AccessAuditService(tx.access_logs).record(
            AccessLogEntry(
                workspace_id=principal.workspace_id,
                session_id=internal_session_id,
                principal_class=ActorClass.HUMAN,
                principal_id=principal.user_id,
                resource_kind=AuditResourceKind.SESSION,
                resource_id=internal_session_id,
                result=AccessResult.ALLOWED,
                scope_ids=("audit:read", f"audit:{body.question.value}"),
                source_ip=source_ip,
                trace_id=str(request.state.correlation_id),
                recorded_at=datetime.now(UTC),
            )
        )
        response = AuditResponse.model_validate(
            {
                "data": {
                    "question": body.question,
                    "question_text": _QUESTIONS[body.question],
                    "parameters": {
                        **{"session_id": public_id("session", internal_session_id)},
                        **{
                            key: value
                            for key, value in body.model_dump(mode="json").items()
                            if key != "question" and value is not None
                        },
                    },
                    "answer": answer,
                    "evidence": evidence,
                    "state": state,
                    "pagination": pagination,
                    "links": _links(),
                },
                "meta": {
                    "request_id": str(request.state.correlation_id),
                    "schema_version": 1,
                    "workspace_id": public_id("workspace", principal.workspace_id),
                },
            }
        )
    return JSONResponse(response.model_dump(mode="json"))
