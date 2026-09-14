"""Deterministic validation and atomic coordinator commit of agent proposals."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, field_validator, model_validator

from app.application.artifact_commit import (
    ArtifactCommitService,
    ArtifactEventContext,
    ArtifactWriteResult,
)
from app.domain.agent_activity import AgentTurnResult, ArtifactProposal
from app.domain.artifact_commit import AgentProposalStore, ArtifactCommitError
from app.domain.critique import ArtifactRevisionProposal, CritiqueAssignment, validate_critic_bundle
from app.domain.reasoning import (
    ActorClass,
    ArtifactKind,
    ArtifactPayload,
    CritiquePayload,
    FrozenModel,
    GraphEdgeType,
    LifecycleStatus,
    ParentRelationship,
    Provenance,
    ProvenanceOrigin,
    ReasoningArtifact,
    Resolution,
    artifact_content_hash,
    content_hash,
    validate_artifact,
    validate_artifact_payload,
)
from app.domain.reasoning_graph import ReasoningGraphWriter
from app.domain.reasoning_ledger import AgentProposalLedger, LedgerAppend, LedgerEvent
from app.ports.agent_runtime import ReasoningContext

__all__ = [
    "AgentProposalCommitter",
    "AgentTurnCommit",
    "agent_turn_commit_id",
    "proposal_references",
]


# trace: FR-210
def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("committed_at must include an RFC 3339 offset")
    return value.astimezone(UTC)


class AgentTurnCommit(FrozenModel):
    """Complete caller-transaction-scoped command for one accepted logical turn."""

    context: ReasoningContext
    result: AgentTurnResult
    committed_at: datetime
    schema_version: int = 1

    _committed_at_utc = field_validator("committed_at")(_aware_utc)

    @model_validator(mode="after")
    def matching_turn(self) -> AgentTurnCommit:
        if self.schema_version != 1:
            raise ValueError("unsupported AgentTurnCommit schema_version")
        if self.result.turn_id != self.context.turn_id:
            raise ValueError("activity result does not match coordinator turn")
        if self.result.agent_definition_id != self.context.agent_definition_id:
            raise ValueError("activity result does not match pinned agent definition")
        return self


def agent_turn_commit_id(turn_id: UUID, proposal_index: int, role: str, ordinal: int = 0) -> UUID:
    """Derive one retry-stable coordinator-owned write identity."""
    if proposal_index < 0 or ordinal < 0 or not role.strip():
        raise ValueError("proposal commit identity inputs are invalid")
    return uuid5(NAMESPACE_URL, f"agora:{turn_id}:{proposal_index}:{role}:{ordinal}")


def _contract_hash(value: BaseModel) -> str:
    """Hash strict contract JSON while representing its allowed floats as decimal strings."""
    return content_hash(json.loads(value.model_dump_json(), parse_float=str))


class AgentProposalCommitter:
    """Preflight a complete bundle, then write through one caller-owned transaction."""

    def __init__(
        self,
        artifacts: AgentProposalStore,
        graph: ReasoningGraphWriter,
        ledger: AgentProposalLedger,
    ) -> None:
        self._artifacts = artifacts
        self._graph = graph
        self._ledger = ledger
        self._commits = ArtifactCommitService(artifacts, graph, ledger)

    async def commit(
        self,
        command: AgentTurnCommit,
        *,
        critique_assignment: CritiqueAssignment | None = None,
    ) -> tuple[ArtifactWriteResult, ...]:
        """Commit proposal order exactly; an exception must roll back the caller transaction."""
        validated = tuple(
            (proposal, validate_artifact_payload(proposal.kind, proposal.payload))
            for proposal in command.result.bundle.artifacts
        )
        _validate_agent_critique_contract(command, validated, critique_assignment)
        await self._artifacts.lock_agent_turn(
            command.context.workspace_id, command.context.session_id, command.context.turn_id
        )
        prepared = tuple(
            self._artifact(command, proposal, payload, index)
            for index, (proposal, payload) in enumerate(validated)
        )
        existing = tuple(
            [
                await self._artifacts.get_for_update(
                    artifact.workspace_id, artifact.session_id, artifact.id
                )
                for artifact in prepared
            ]
        )
        prior_nodes = tuple(
            [
                await self._graph.node_for_artifact(
                    artifact.workspace_id, artifact.session_id, artifact.id
                )
                for artifact in prepared
            ]
        )
        prior_events = tuple(
            [
                await self._ledger.get_by_id(
                    artifact.workspace_id,
                    artifact.session_id,
                    agent_turn_commit_id(command.context.turn_id, index, "event"),
                )
                for index, artifact in enumerate(prepared)
            ]
        )
        completion = await self._ledger.get_by_id(
            command.context.workspace_id,
            command.context.session_id,
            agent_turn_commit_id(command.context.turn_id, 0, "turn-event"),
        )
        if any(value is not None for value in (*existing, *prior_nodes, *prior_events, completion)):
            return await self._idempotent_result(command, prepared, existing, completion)
        await self._preflight(command.context, validated)

        writes: list[ArtifactWriteResult] = []
        for index, artifact in enumerate(prepared):
            write = await self._commits.commit(
                artifact,
                node_id=agent_turn_commit_id(command.context.turn_id, index, "node"),
                relationship_edge_ids=tuple(
                    agent_turn_commit_id(
                        command.context.turn_id, index, "relationship-edge", ordinal
                    )
                    for ordinal, _relationship in enumerate(artifact.parent_relationships)
                ),
                label=artifact.kind.value.replace("_", " ").title(),
                context=ArtifactEventContext(
                    event_id=agent_turn_commit_id(command.context.turn_id, index, "event"),
                    correlation_id=command.context.correlation_id,
                    causation_id=command.context.causation_id,
                    actor_class=ActorClass.AGENT,
                    actor_id=command.context.agent_definition_id,
                    recorded_at=command.committed_at,
                ),
            )
            writes.append(write)
        await self._ledger.append(_completion_event(command, prepared))
        return tuple(writes)

    async def _idempotent_result(
        self,
        command: AgentTurnCommit,
        expected: tuple[ReasoningArtifact, ...],
        existing: tuple[ReasoningArtifact | None, ...],
        completion: LedgerEvent | None,
    ) -> tuple[ArtifactWriteResult, ...]:
        if len(existing) != len(expected) or any(artifact is None for artifact in existing):
            raise ArtifactCommitError("agent turn has an incomplete prior commit")
        committed: list[ArtifactWriteResult] = []
        for index, (wanted, found) in enumerate(zip(expected, existing, strict=True)):
            assert found is not None
            if found.content_hash != wanted.content_hash:
                raise ArtifactCommitError(
                    "agent turn identity conflicts with persisted artifact content"
                )
            node = await self._graph.node_for_artifact(
                wanted.workspace_id, wanted.session_id, wanted.id
            )
            if node is None or node.id != agent_turn_commit_id(
                command.context.turn_id, index, "node"
            ):
                raise ArtifactCommitError("agent turn has an incomplete graph projection")
            event = await self._ledger.get_by_id(
                wanted.workspace_id,
                wanted.session_id,
                agent_turn_commit_id(command.context.turn_id, index, "event"),
            )
            if event is None or not _event_matches(event, wanted, command):
                raise ArtifactCommitError(
                    "agent turn has an incomplete or conflicting ledger event"
                )
            committed.append(ArtifactWriteResult(artifact=found, event=event))
        if completion is None or not _completion_matches(completion, command, expected):
            raise ArtifactCommitError(
                "agent turn has an incomplete or conflicting completion event"
            )
        return tuple(committed)

    async def _preflight(
        self,
        context: ReasoningContext,
        validated: tuple[tuple[ArtifactProposal, ArtifactPayload], ...],
    ) -> None:
        references: dict[UUID, set[ArtifactKind]] = {}
        for proposal, payload in validated:
            for reference_id, expected in proposal_references(proposal, payload):
                required = references.setdefault(reference_id, set())
                if expected is not None:
                    required.update(expected)

        unauthorized = set(references).difference(context.visible_artifact_ids)
        if unauthorized:
            reference_id = min(unauthorized, key=lambda value: value.int)
            raise ArtifactCommitError(
                f"proposal artifact reference {reference_id} was not authorized for the turn"
            )
        for reference_id in sorted(references, key=lambda value: value.int):
            expected = references[reference_id]
            snapshot = next(
                artifact for artifact in context.visible_artifacts if artifact.id == reference_id
            )
            artifact = await self._artifacts.get_for_update(
                context.workspace_id, context.session_id, reference_id
            )
            if artifact is None:
                raise ArtifactCommitError(
                    f"proposal artifact reference {reference_id} does not exist "
                    "in the tenant session"
                )
            if artifact.status is not LifecycleStatus.ACTIVE:
                raise ArtifactCommitError(
                    f"proposal artifact reference {reference_id} is not ACTIVE"
                )
            if artifact.round > context.round:
                raise ArtifactCommitError(
                    f"proposal artifact reference {reference_id} is from the future"
                )
            if (
                artifact.kind.value != snapshot.kind
                or artifact.owner_actor_class.value != snapshot.owner_actor_class
                or artifact.owner_actor_id != snapshot.owner_actor_id
                or artifact.round != snapshot.round
                or artifact.content_hash != snapshot.content_hash
            ):
                raise ArtifactCommitError(
                    f"proposal artifact reference {reference_id} does not match its turn snapshot"
                )
            if expected and artifact.kind not in expected:
                kinds = ", ".join(sorted(kind.value for kind in expected))
                raise ArtifactCommitError(
                    f"proposal artifact reference {reference_id} must have kind {kinds}"
                )

    @staticmethod
    def _artifact(
        command: AgentTurnCommit,
        proposal: ArtifactProposal,
        payload: ArtifactPayload,
        index: int,
    ) -> ReasoningArtifact:
        context, result = command.context, command.result
        artifact_id = agent_turn_commit_id(context.turn_id, index, "artifact")
        attribution = _attribution(command)
        metadata: dict[str, Any] = {"attribution": attribution}
        if proposal.evidence_disposition is not None:
            metadata["evidence_disposition"] = proposal.evidence_disposition.value
        parent_relationships: tuple[ParentRelationship, ...] = ()
        if proposal.kind is ArtifactKind.CRITIQUE:
            if not isinstance(payload, CritiquePayload):
                raise TypeError("validated CRITIQUE payload has an unexpected type")
            parent_relationships = (
                ParentRelationship(
                    edge_type=GraphEdgeType.ATTACKS,
                    target_artifact_id=payload.target_id,
                ),
            )
        values: dict[str, Any] = {
            "id": artifact_id,
            "workspace_id": context.workspace_id,
            "session_id": context.session_id,
            "logical_id": artifact_id,
            "kind": proposal.kind,
            "schema_version": 1,
            "version": 1,
            "status": LifecycleStatus.ACTIVE,
            "supersedes_id": None,
            "owner_actor_class": ActorClass.AGENT,
            "owner_actor_id": context.agent_definition_id,
            "round": context.round,
            "payload": payload,
            "provenance": Provenance(
                origin=ProvenanceOrigin.LLM,
                reference=result.raw_artifact_ref,
                model_call_id=context.turn_id,
                activity_id=context.turn_id,
            ),
            "source_references": (),
            "parent_relationships": parent_relationships,
            "confidence": proposal.confidence,
            "metadata": metadata,
            "created_at": command.committed_at,
            "updated_at": command.committed_at,
        }
        values["content_hash"] = artifact_content_hash(values)
        return validate_artifact(values)


def proposal_references(
    proposal: ArtifactProposal | ArtifactRevisionProposal, payload: ArtifactPayload
) -> tuple[tuple[UUID, set[ArtifactKind] | None], ...]:
    """Return every authoritative envelope/payload reference with required target kinds."""
    references: list[tuple[UUID, set[ArtifactKind] | None]] = []
    data = payload.model_dump(mode="python")

    def add(field: str, expected: set[ArtifactKind] | None = None) -> None:
        value = data.get(field)
        if isinstance(value, UUID):
            references.append((value, expected))
        elif isinstance(value, tuple | list):
            references.extend((item, expected) for item in value if isinstance(item, UUID))

    if proposal.kind is ArtifactKind.CLAIM:
        add("supporting_evidence_ids", {ArtifactKind.EVIDENCE})
        add("opposing_evidence_ids", {ArtifactKind.EVIDENCE})
    elif proposal.kind is ArtifactKind.EVIDENCE:
        add("claim_id", {ArtifactKind.CLAIM})
    elif proposal.kind is ArtifactKind.INFERENCE:
        add("premise_ids")
        add("conclusion_id")
    elif proposal.kind is ArtifactKind.UNCERTAINTY:
        add("target_id")
    elif proposal.kind is ArtifactKind.RISK:
        add("uncertainty_id", {ArtifactKind.UNCERTAINTY})
        add("affected_objective_ids", {ArtifactKind.OBJECTIVE})
    elif proposal.kind is ArtifactKind.IMPACT:
        add("alternative_id", {ArtifactKind.ALTERNATIVE})
        add("objective_id", {ArtifactKind.OBJECTIVE})
        add("source_artifact_id")
    elif proposal.kind is ArtifactKind.OBJECTIVE:
        add("conflicts_with_ids", {ArtifactKind.OBJECTIVE})
    elif proposal.kind is ArtifactKind.POSITION:
        add("target_id", {ArtifactKind.PROPOSITION})
        add("evidence_ids", {ArtifactKind.EVIDENCE})
    elif proposal.kind is ArtifactKind.CRITIQUE:
        add("target_id")

    if proposal.confidence is not None:
        references.extend((value, None) for value in proposal.confidence.basis_artifact_ids)
    return tuple(references)


def _validate_agent_critique_contract(
    command: AgentTurnCommit,
    validated: tuple[tuple[ArtifactProposal, ArtifactPayload], ...],
    assignment: CritiqueAssignment | None,
) -> None:
    context, bundle = command.context, command.result.bundle
    contains_critique = any(
        proposal.kind is ArtifactKind.CRITIQUE for proposal, _payload in validated
    )
    critique_role = context.agent_definition.role_kind in {"critic", "domain_expert"}
    dedicated_critic = context.agent_definition.role_kind == "critic"
    critique_phase = context.phase.value == "CRITIQUE"
    if not (contains_critique or dedicated_critic or critique_phase):
        if assignment is not None:
            raise ArtifactCommitError("Critique assignment is invalid outside CRITIQUE phase")
        return
    if not critique_role or not critique_phase:
        raise ArtifactCommitError(
            "agent Critique commit requires a critic or domain expert in CRITIQUE phase"
        )
    if assignment is None:
        raise ArtifactCommitError("agent Critique commit requires a coordinator assignment")
    pins = (
        context.workspace_id,
        context.session_id,
        context.agent_definition_id,
        context.agent_definition_version,
        context.turn_id,
        context.correlation_id,
        context.causation_id,
        context.round,
        context.visible_artifact_ids,
    )
    expected = (
        assignment.workspace_id,
        assignment.session_id,
        assignment.critic_definition_id,
        assignment.critic_definition_version,
        assignment.turn_id,
        assignment.correlation_id,
        assignment.causation_id,
        assignment.round,
        assignment.target_artifact_ids,
    )
    if pins != expected:
        raise ArtifactCommitError("Critique assignment does not match authorized reasoning context")
    try:
        validate_critic_bundle(bundle, assignment)
    except ValueError as exc:
        raise ArtifactCommitError(str(exc)) from exc
    for proposal, payload in validated:
        if proposal.kind is not ArtifactKind.CRITIQUE or not isinstance(payload, CritiquePayload):
            raise ArtifactCommitError("Critic bundle may contain only CRITIQUE proposals")
        if payload.resolution is not Resolution.OPEN:
            raise ArtifactCommitError("new Critique proposals must have OPEN resolution")


def _event_matches(
    event: LedgerEvent, artifact: ReasoningArtifact, command: AgentTurnCommit
) -> bool:
    return (
        event.event_type == "ARTIFACT_COMMITTED"
        and event.workspace_id == artifact.workspace_id
        and event.session_id == artifact.session_id
        and event.causation_id == command.context.causation_id
        and event.correlation_id == command.context.correlation_id
        and event.actor_class is ActorClass.AGENT
        and event.actor_id == command.context.agent_definition_id
        and event.round == command.context.round
        and event.recorded_at == command.committed_at
        and event.payload.get("artifact_id") == str(artifact.id)
        and event.payload.get("kind") == artifact.kind.value
        and event.payload.get("logical_id") == str(artifact.logical_id)
        and event.payload.get("version") == artifact.version
        and event.payload.get("attribution") == artifact.metadata.get("attribution")
        and event.payload.get("evidence_disposition")
        == artifact.metadata.get("evidence_disposition")
    )


def _attribution(command: AgentTurnCommit) -> dict[str, Any]:
    context, result = command.context, command.result
    return {
        "agent_definition_id": str(context.agent_definition_id),
        "agent_definition_version": context.agent_definition_version,
        "strategy_name": context.strategy_name,
        "strategy_version": context.strategy_version,
        "provider": result.provider,
        "model": result.model,
        "prompt_ref": context.agent_definition.prompt_ref,
        "prompt_hash": context.agent_definition.prompt_hash,
        "round": context.round,
        "phase": context.phase.value,
        "turn_id": str(context.turn_id),
        "correlation_id": str(context.correlation_id),
        "causation_id": str(context.causation_id),
        "raw_artifact_ref": result.raw_artifact_ref,
        "context_hash": _contract_hash(context),
        "bundle_hash": _contract_hash(result.bundle),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": str(result.cost_usd),
        "committed_at": command.committed_at.isoformat().replace("+00:00", "Z"),
    }


def _completion_event(
    command: AgentTurnCommit, artifacts: tuple[ReasoningArtifact, ...]
) -> LedgerAppend:
    context = command.context
    return LedgerAppend(
        id=agent_turn_commit_id(context.turn_id, 0, "turn-event"),
        workspace_id=context.workspace_id,
        session_id=context.session_id,
        event_type="AGENT_TURN_COMPLETED",
        payload_schema_version=1,
        causation_id=context.causation_id,
        correlation_id=context.correlation_id,
        actor_class=ActorClass.AGENT,
        actor_id=context.agent_definition_id,
        round=context.round,
        payload={
            "turn_id": str(context.turn_id),
            "artifact_ids": [str(artifact.id) for artifact in artifacts],
            "proposal_count": len(artifacts),
            "attribution": _attribution(command),
        },
        recorded_at=command.committed_at,
    )


def _completion_matches(
    event: LedgerEvent,
    command: AgentTurnCommit,
    artifacts: tuple[ReasoningArtifact, ...],
) -> bool:
    expected = _completion_event(command, artifacts)
    return (
        event.id == expected.id
        and event.event_type == expected.event_type
        and event.workspace_id == expected.workspace_id
        and event.session_id == expected.session_id
        and event.causation_id == expected.causation_id
        and event.correlation_id == expected.correlation_id
        and event.actor_class is expected.actor_class
        and event.actor_id == expected.actor_id
        and event.round == expected.round
        and event.recorded_at == expected.recorded_at
        and event.payload == expected.payload
    )
