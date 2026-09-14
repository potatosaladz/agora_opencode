"""Atomic coordinator commit of Phase 7 Critique responses and target revisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, field_validator, model_validator

from app.application.artifact_commit import ArtifactCommitService, ArtifactEventContext
from app.application.proposal_commit import proposal_references
from app.domain.artifact_commit import ArtifactCommitError, ReasoningArtifactStore
from app.domain.critique import (
    CritiqueResponseDisposition,
    CritiqueResponseProposal,
    CritiqueResponseRequest,
    CritiqueResponseResult,
    CritiqueResponseResultStatus,
    CritiqueResponseStore,
    critique_response_request_hash,
)
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
    validate_artifact,
    validate_artifact_payload,
)
from app.domain.reasoning_graph import ReasoningGraphWriter
from app.domain.reasoning_ledger import AgentProposalLedger, LedgerAppend
from app.ports.agent_runtime import ReasoningContext, ReasoningPhase, TurnExecutionResult

__all__ = ["CritiqueResponseCommand", "CritiqueResponseCommitter", "response_commit_id"]


# trace: FR-503
def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("committed_at must include an RFC 3339 offset")
    return value.astimezone(UTC)


class CritiqueResponseCommand(FrozenModel):
    """Complete caller-transaction-scoped command for one agent response."""

    context: ReasoningContext
    execution: TurnExecutionResult[CritiqueResponseProposal]
    committed_at: datetime
    schema_version: int = 1

    _committed_at_utc = field_validator("committed_at")(_aware_utc)

    @model_validator(mode="after")
    def matching_pins(self) -> CritiqueResponseCommand:
        if self.schema_version != 1:
            raise ValueError("unsupported CritiqueResponseCommand schema_version")
        proposal = self.execution.proposal
        context = self.context
        if context.phase is not ReasoningPhase.REVISE:
            raise ValueError("Critique response requires REVISE phase")
        if not context.sealed:
            raise ValueError("Critique response requires a sealed author-specific context")
        actual = (
            proposal.workspace_id,
            proposal.session_id,
            proposal.responding_definition_id,
            proposal.responding_definition_version,
            proposal.turn_id,
            proposal.correlation_id,
            proposal.causation_id,
            proposal.round,
        )
        expected = (
            context.workspace_id,
            context.session_id,
            context.agent_definition_id,
            context.agent_definition_version,
            context.turn_id,
            context.correlation_id,
            context.causation_id,
            context.round,
        )
        if actual != expected:
            raise ValueError("Critique response does not match its authorized reasoning context")
        return self


def response_commit_id(response_id: UUID, role: str, ordinal: int = 0) -> UUID:
    """Derive one retry-stable coordinator-owned response effect identity."""
    if not role.strip() or ordinal < 0:
        raise ValueError("response commit identity inputs are invalid")
    return uuid5(NAMESPACE_URL, f"agora:critique-response:{response_id}:{role}:{ordinal}")


_RESOLUTION_BY_DISPOSITION = {
    CritiqueResponseDisposition.ACCEPT: Resolution.RESOLVED,
    CritiqueResponseDisposition.PARTIALLY_ACCEPT: Resolution.UNRESOLVED,
    CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION: Resolution.DISPUTED,
    CritiqueResponseDisposition.REVISE: Resolution.RESOLVED,
    CritiqueResponseDisposition.REQUEST_EVIDENCE: Resolution.UNRESOLVED,
    CritiqueResponseDisposition.REQUEST_SIMULATION: Resolution.UNRESOLVED,
    CritiqueResponseDisposition.ABSTAIN: Resolution.UNRESOLVED,
}

_STATUS_BY_DISPOSITION = {
    CritiqueResponseDisposition.ACCEPT: CritiqueResponseResultStatus.RESOLVED,
    CritiqueResponseDisposition.PARTIALLY_ACCEPT: CritiqueResponseResultStatus.UNRESOLVED,
    CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION: CritiqueResponseResultStatus.DISPUTED,
    CritiqueResponseDisposition.REVISE: CritiqueResponseResultStatus.REVISED,
    CritiqueResponseDisposition.REQUEST_EVIDENCE: (CritiqueResponseResultStatus.EVIDENCE_REQUESTED),
    CritiqueResponseDisposition.REQUEST_SIMULATION: (
        CritiqueResponseResultStatus.SIMULATION_DEFERRED
    ),
    CritiqueResponseDisposition.ABSTAIN: CritiqueResponseResultStatus.ABSTAINED,
}


class CritiqueResponseCommitter:
    """Preflight complete response effects, then append them through one transaction."""

    def __init__(
        self,
        artifacts: ReasoningArtifactStore,
        graph: ReasoningGraphWriter,
        ledger: AgentProposalLedger,
        responses: CritiqueResponseStore,
    ) -> None:
        self._artifacts = artifacts
        self._graph = graph
        self._ledger = ledger
        self._responses = responses
        self._commits = ArtifactCommitService(artifacts, graph, ledger)

    async def commit(self, command: CritiqueResponseCommand) -> CritiqueResponseResult:
        proposal = command.execution.proposal
        request = _request(command)
        await self._responses.lock_response(
            proposal.workspace_id, proposal.session_id, proposal.response_id
        )
        existing_request = await self._responses.get_request(
            proposal.workspace_id, proposal.session_id, proposal.response_id
        )
        existing_result = await self._responses.get_result(
            proposal.workspace_id, proposal.session_id, proposal.response_id
        )
        if existing_request is not None or existing_result is not None:
            if existing_request != request or existing_result is None:
                raise ArtifactCommitError(
                    "response identity has an incomplete or conflicting prior commit"
                )
            expected_result = _result(command)
            if existing_result != expected_result:
                raise ArtifactCommitError(
                    "response identity has an incomplete or conflicting prior result"
                )
            return await self._idempotent_result(existing_result)

        artifacts = await self._preflight(command)
        critique = artifacts[proposal.critique_id]
        target = artifacts[proposal.target_artifact_id]
        critique_revision = _critique_revision(command, critique, target)
        resolution = _RESOLUTION_BY_DISPOSITION[proposal.disposition]
        target_revision = _target_revision(command, target) if proposal.proposed_revision else None

        await self._responses.add_request(request)
        await self._commits.revise(
            critique_revision,
            node_id=response_commit_id(proposal.response_id, "critique-node"),
            edge_id=response_commit_id(proposal.response_id, "critique-supersedes-edge"),
            relationship_edge_ids=(
                response_commit_id(proposal.response_id, "critique-attacks-edge"),
            ),
            label="Critique",
            reason=f"Critique response {proposal.disposition.value}",
            context=_event_context(command, "critique-revision-event"),
        )
        if target_revision is not None:
            relationship_ids = tuple(
                response_commit_id(proposal.response_id, "target-relationship-edge", index)
                for index, _ in enumerate(target_revision.parent_relationships)
            )
            await self._commits.revise(
                target_revision,
                node_id=response_commit_id(proposal.response_id, "target-node"),
                edge_id=response_commit_id(proposal.response_id, "target-supersedes-edge"),
                relationship_edge_ids=relationship_ids,
                label=target_revision.kind.value.replace("_", " ").title(),
                reason=f"Response to Critique {proposal.critique_id}",
                context=_event_context(command, "target-revision-event"),
            )

        event_id = response_commit_id(proposal.response_id, "response-event")
        await self._ledger.append(
            LedgerAppend(
                id=event_id,
                workspace_id=proposal.workspace_id,
                session_id=proposal.session_id,
                event_type="CRITIQUE_RESPONDED",
                payload_schema_version=1,
                causation_id=proposal.causation_id,
                correlation_id=proposal.correlation_id,
                actor_class=ActorClass.AGENT,
                actor_id=proposal.responding_definition_id,
                round=proposal.round,
                payload={
                    "response_id": str(proposal.response_id),
                    "request_hash": request.request_hash,
                    "disposition": proposal.disposition.value,
                    "result_status": _STATUS_BY_DISPOSITION[proposal.disposition].value,
                    "resolution": resolution.value,
                    "critique_id": str(proposal.critique_id),
                    "critique_revision_id": str(critique_revision.id),
                    "target_artifact_id": str(proposal.target_artifact_id),
                    "target_revision_id": str(target_revision.id)
                    if target_revision is not None
                    else None,
                    "warrant_artifact_ids": [str(value) for value in proposal.warrant_artifact_ids],
                    "attribution": _attribution(command),
                },
                recorded_at=command.committed_at,
            )
        )
        result = _result(command)
        await self._responses.add_result(result)
        return result

    async def _idempotent_result(self, result: CritiqueResponseResult) -> CritiqueResponseResult:
        expected = [
            (
                result.critique_revision_id,
                result.critique_revision_version,
                response_commit_id(result.response_id, "critique-node"),
            )
        ]
        if result.target_revision_id is not None:
            assert result.target_revision_version is not None
            expected.append(
                (
                    result.target_revision_id,
                    result.target_revision_version,
                    response_commit_id(result.response_id, "target-node"),
                )
            )
        for artifact_id, version, node_id in expected:
            artifact = await self._artifacts.get_for_update(
                result.workspace_id, result.session_id, artifact_id
            )
            node = await self._graph.node_for_artifact(
                result.workspace_id, result.session_id, artifact_id
            )
            if (
                artifact is None
                or artifact.version != version
                or node is None
                or node.id != node_id
            ):
                raise ArtifactCommitError("response has an incomplete prior artifact commit")
        event = await self._ledger.get_by_id(
            result.workspace_id, result.session_id, result.response_event_id
        )
        if (
            event is None
            or event.event_type != "CRITIQUE_RESPONDED"
            or event.payload.get("response_id") != str(result.response_id)
        ):
            raise ArtifactCommitError("response has an incomplete prior ledger commit")
        return result

    async def _preflight(self, command: CritiqueResponseCommand) -> dict[UUID, ReasoningArtifact]:
        proposal = command.execution.proposal
        visible = set(command.context.visible_artifact_ids)
        required = {
            proposal.critique_id,
            proposal.target_artifact_id,
            *proposal.warrant_artifact_ids,
        }
        if not required.issubset(visible):
            raise ArtifactCommitError(
                "Critique response references an artifact not authorized for the turn"
            )

        artifacts: dict[UUID, ReasoningArtifact] = {}
        for artifact_id in sorted(required, key=lambda value: value.int):
            artifact = await self._artifacts.get_for_update(
                proposal.workspace_id, proposal.session_id, artifact_id
            )
            if artifact is None:
                raise ArtifactCommitError(
                    f"response artifact reference {artifact_id} does not exist "
                    "in the tenant session"
                )
            snapshot = next(
                value for value in command.context.visible_artifacts if value.id == artifact_id
            )
            if (
                artifact.kind.value != snapshot.kind
                or artifact.owner_actor_class.value != snapshot.owner_actor_class
                or artifact.owner_actor_id != snapshot.owner_actor_id
                or artifact.round != snapshot.round
                or artifact.content_hash != snapshot.content_hash
            ):
                raise ArtifactCommitError(
                    f"response artifact reference {artifact_id} does not match its turn snapshot"
                )
            if artifact.round > proposal.round:
                raise ArtifactCommitError(
                    f"response artifact reference {artifact_id} is from the future"
                )
            if (
                await self._graph.node_for_artifact(
                    proposal.workspace_id, proposal.session_id, artifact_id
                )
                is None
            ):
                raise ArtifactCommitError(
                    f"response artifact reference {artifact_id} has no graph projection"
                )
            artifacts[artifact_id] = artifact

        critique = artifacts[proposal.critique_id]
        target = artifacts[proposal.target_artifact_id]
        if critique.kind is not ArtifactKind.CRITIQUE or not isinstance(
            critique.payload, CritiquePayload
        ):
            raise ArtifactCommitError("response critique reference is not a CRITIQUE")
        if (
            critique.version != proposal.critique_version
            or critique.status is not LifecycleStatus.ACTIVE
        ):
            raise ArtifactCommitError("response Critique head is stale")
        if critique.payload.resolution is Resolution.RESOLVED:
            raise ArtifactCommitError("a resolved Critique cannot receive another response")
        if critique.payload.target_id != target.id:
            raise ArtifactCommitError("response target does not match the Critique target")
        if (
            target.version != proposal.target_artifact_version
            or target.status is not LifecycleStatus.ACTIVE
        ):
            raise ArtifactCommitError("response target head is stale")
        if target.owner_actor_class is not ActorClass.AGENT:
            raise ArtifactCommitError(
                "only an AGENT-owned target may receive an automatic response"
            )
        if target.owner_actor_id != proposal.responding_definition_id:
            raise ArtifactCommitError("responding agent does not own the Critique target")
        if proposal.disposition is CritiqueResponseDisposition.REJECT_WITH_JUSTIFICATION:
            for warrant_id in proposal.warrant_artifact_ids:
                if warrant_id in {critique.id, target.id}:
                    raise ArtifactCommitError(
                        "response warrant must be independent of Critique and target"
                    )
                if artifacts[warrant_id].status is not LifecycleStatus.ACTIVE:
                    raise ArtifactCommitError("response warrant is not ACTIVE")
        if proposal.proposed_revision is not None:
            await self._preflight_revision_references(command, artifacts)
        return artifacts

    async def _preflight_revision_references(
        self,
        command: CritiqueResponseCommand,
        artifacts: dict[UUID, ReasoningArtifact],
    ) -> None:
        proposal = command.execution.proposal
        revision = proposal.proposed_revision
        assert revision is not None
        payload = validate_artifact_payload(revision.kind, revision.payload)
        for reference_id, expected in proposal_references(revision, payload):
            if reference_id not in command.context.visible_artifact_ids:
                raise ArtifactCommitError(
                    f"revision artifact reference {reference_id} was not authorized for the turn"
                )
            artifact = artifacts.get(reference_id)
            if artifact is None:
                artifact = await self._artifacts.get_for_update(
                    proposal.workspace_id, proposal.session_id, reference_id
                )
                if artifact is None or artifact.status is not LifecycleStatus.ACTIVE:
                    raise ArtifactCommitError(
                        f"revision artifact reference {reference_id} is missing or inactive"
                    )
                artifacts[reference_id] = artifact
            snapshot = next(
                value for value in command.context.visible_artifacts if value.id == reference_id
            )
            if (
                artifact.kind.value != snapshot.kind
                or artifact.owner_actor_class.value != snapshot.owner_actor_class
                or artifact.owner_actor_id != snapshot.owner_actor_id
                or artifact.round != snapshot.round
                or artifact.content_hash != snapshot.content_hash
            ):
                raise ArtifactCommitError(
                    f"revision artifact reference {reference_id} does not match its turn snapshot"
                )
            if artifact.round > proposal.round:
                raise ArtifactCommitError(
                    f"revision artifact reference {reference_id} is from the future"
                )
            if (
                await self._graph.node_for_artifact(
                    proposal.workspace_id, proposal.session_id, reference_id
                )
                is None
            ):
                raise ArtifactCommitError(
                    f"revision artifact reference {reference_id} has no graph projection"
                )
            if expected and artifact.kind not in expected:
                kinds = ", ".join(sorted(kind.value for kind in expected))
                raise ArtifactCommitError(
                    f"revision artifact reference {reference_id} must have kind {kinds}"
                )


def _event_context(command: CritiqueResponseCommand, role: str) -> ArtifactEventContext:
    proposal = command.execution.proposal
    return ArtifactEventContext(
        event_id=response_commit_id(proposal.response_id, role),
        correlation_id=proposal.correlation_id,
        causation_id=proposal.causation_id,
        actor_class=ActorClass.AGENT,
        actor_id=proposal.responding_definition_id,
        recorded_at=command.committed_at,
    )


def _request(command: CritiqueResponseCommand) -> CritiqueResponseRequest:
    proposal = command.execution.proposal
    payload = proposal.model_dump(mode="json")
    execution = _attribution(command)
    return CritiqueResponseRequest(
        response_id=proposal.response_id,
        workspace_id=proposal.workspace_id,
        session_id=proposal.session_id,
        turn_id=proposal.turn_id,
        responding_definition_id=proposal.responding_definition_id,
        responding_definition_version=proposal.responding_definition_version,
        critique_id=proposal.critique_id,
        critique_version=proposal.critique_version,
        target_artifact_id=proposal.target_artifact_id,
        target_artifact_version=proposal.target_artifact_version,
        disposition=proposal.disposition,
        request_hash=critique_response_request_hash(payload, execution, command.committed_at),
        request_payload=payload,
        execution_metadata=execution,
        requested_at=command.committed_at,
    )


def _attribution(command: CritiqueResponseCommand) -> dict[str, Any]:
    context = command.context
    return {
        "agent_definition_id": str(context.agent_definition_id),
        "agent_definition_version": context.agent_definition_version,
        "strategy_name": context.strategy_name,
        "strategy_version": context.strategy_version,
        "provider": command.execution.provider,
        "model": command.execution.model,
        "prompt_ref": context.agent_definition.prompt_ref,
        "prompt_hash": context.agent_definition.prompt_hash,
        "round": context.round,
        "phase": context.phase.value,
        "turn_id": str(context.turn_id),
        "correlation_id": str(context.correlation_id),
        "causation_id": str(context.causation_id),
        "raw_artifact_ref": command.execution.raw_artifact_ref,
        "context_hash": _contract_hash(context),
        "response_hash": _contract_hash(command.execution.proposal),
        "input_tokens": command.execution.input_tokens,
        "output_tokens": command.execution.output_tokens,
        "cost_usd": str(command.execution.cost_usd),
        "committed_at": command.committed_at.isoformat().replace("+00:00", "Z"),
    }


def _contract_hash(value: BaseModel) -> str:
    from app.domain.reasoning import content_hash

    return content_hash(json.loads(value.model_dump_json(), parse_float=str))


def _result(command: CritiqueResponseCommand) -> CritiqueResponseResult:
    proposal = command.execution.proposal
    revised = proposal.disposition is CritiqueResponseDisposition.REVISE
    return CritiqueResponseResult(
        response_id=proposal.response_id,
        workspace_id=proposal.workspace_id,
        session_id=proposal.session_id,
        status=_STATUS_BY_DISPOSITION[proposal.disposition],
        disposition=proposal.disposition,
        resolution=_RESOLUTION_BY_DISPOSITION[proposal.disposition],
        critique_revision_id=response_commit_id(proposal.response_id, "critique-revision"),
        critique_revision_version=proposal.critique_version + 1,
        target_revision_id=response_commit_id(proposal.response_id, "target-revision")
        if revised
        else None,
        target_revision_version=proposal.target_artifact_version + 1 if revised else None,
        response_event_id=response_commit_id(proposal.response_id, "response-event"),
        committed_at=command.committed_at,
    )


def _revision_values(
    command: CritiqueResponseCommand,
    previous: ReasoningArtifact,
    *,
    artifact_id: UUID,
    payload: ArtifactPayload,
    parent_relationships: tuple[ParentRelationship, ...],
    confidence: object,
    evidence_disposition: str | None = None,
) -> dict[str, Any]:
    reference = command.execution.raw_artifact_ref or (
        f"deterministic-response:{command.execution.proposal.response_id}"
    )
    metadata = dict(previous.metadata)
    metadata.update(
        {
            "attribution": _attribution(command),
            "response_id": str(command.execution.proposal.response_id),
            "response_disposition": command.execution.proposal.disposition.value,
        }
    )
    if evidence_disposition is not None:
        metadata["evidence_disposition"] = evidence_disposition
    provenance = (
        previous.provenance
        if previous.kind in {ArtifactKind.FACT, ArtifactKind.EVIDENCE}
        else Provenance(
            origin=ProvenanceOrigin.LLM,
            reference=reference,
            model_call_id=command.context.turn_id,
            activity_id=command.context.turn_id,
        )
    )
    values: dict[str, Any] = {
        "id": artifact_id,
        "workspace_id": previous.workspace_id,
        "session_id": previous.session_id,
        "logical_id": previous.logical_id,
        "kind": previous.kind,
        "schema_version": previous.schema_version,
        "version": previous.version + 1,
        "status": LifecycleStatus.ACTIVE,
        "supersedes_id": previous.id,
        "owner_actor_class": previous.owner_actor_class,
        "owner_actor_id": previous.owner_actor_id,
        "round": command.context.round,
        "payload": payload,
        "provenance": provenance,
        "source_references": previous.source_references,
        "parent_relationships": parent_relationships,
        "confidence": confidence,
        "metadata": metadata,
        "created_at": command.committed_at,
        "updated_at": command.committed_at,
    }
    values["content_hash"] = artifact_content_hash(values)
    return values


def _critique_revision(
    command: CritiqueResponseCommand,
    critique: ReasoningArtifact,
    target: ReasoningArtifact,
) -> ReasoningArtifact:
    assert isinstance(critique.payload, CritiquePayload)
    proposal = command.execution.proposal
    payload = critique.payload.model_copy(
        update={"resolution": _RESOLUTION_BY_DISPOSITION[proposal.disposition]}
    )
    return validate_artifact(
        _revision_values(
            command,
            critique,
            artifact_id=response_commit_id(proposal.response_id, "critique-revision"),
            payload=payload,
            parent_relationships=(
                ParentRelationship(edge_type=GraphEdgeType.ATTACKS, target_artifact_id=target.id),
            ),
            confidence=critique.confidence,
        )
    )


def _target_revision(
    command: CritiqueResponseCommand, target: ReasoningArtifact
) -> ReasoningArtifact:
    proposal = command.execution.proposal
    revision = proposal.proposed_revision
    assert revision is not None
    if revision.kind is not target.kind:
        raise ArtifactCommitError("target revision must preserve artifact kind")
    payload = validate_artifact_payload(revision.kind, revision.payload)
    relationships = (
        *(
            relationship
            for relationship in target.parent_relationships
            if relationship.edge_type
            not in {GraphEdgeType.SUPERSEDES, GraphEdgeType.RESPONDS_TO, GraphEdgeType.ATTACKS}
        ),
        *(
            (
                ParentRelationship(
                    edge_type=GraphEdgeType.ATTACKS,
                    target_artifact_id=payload.target_id,
                ),
            )
            if isinstance(payload, CritiquePayload)
            else ()
        ),
        ParentRelationship(
            edge_type=GraphEdgeType.RESPONDS_TO,
            target_artifact_id=proposal.critique_id,
        ),
    )
    return validate_artifact(
        _revision_values(
            command,
            target,
            artifact_id=response_commit_id(proposal.response_id, "target-revision"),
            payload=payload,
            parent_relationships=relationships,
            confidence=revision.confidence,
            evidence_disposition=revision.evidence_disposition.value
            if revision.evidence_disposition is not None
            else None,
        )
    )
