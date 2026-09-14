"""Atomic artifact commit, revision, and withdrawal orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import field_validator

from app.domain.artifact_commit import ArtifactCommitError, ReasoningArtifactStore
from app.domain.reasoning import (
    ActorClass,
    CritiquePayload,
    FrozenModel,
    GraphEdgeType,
    LifecycleStatus,
    ReasoningArtifact,
)
from app.domain.reasoning_graph import GraphEdge, GraphNode, ReasoningGraphWriter
from app.domain.reasoning_ledger import LedgerAppend, LedgerEvent, ReasoningLedger

__all__ = ["ArtifactCommitService", "ArtifactEventContext", "ArtifactWriteResult"]


# trace: FR-302, FR-303
def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


class ArtifactEventContext(FrozenModel):
    """Caller-owned identity, attribution, and time for one lifecycle event."""

    event_id: UUID
    correlation_id: UUID
    causation_id: UUID | None = None
    actor_class: ActorClass
    actor_id: UUID
    recorded_at: datetime

    _recorded_at_utc = field_validator("recorded_at")(_aware_utc)


class ArtifactWriteResult(FrozenModel):
    """Typed artifact state and the durable event produced by one write."""

    artifact: ReasoningArtifact
    event: LedgerEvent


class ArtifactCommitService:
    """Coordinate state, ledger, and graph writes without owning the transaction."""

    def __init__(
        self,
        artifacts: ReasoningArtifactStore,
        graph: ReasoningGraphWriter,
        ledger: ReasoningLedger,
    ) -> None:
        self._artifacts = artifacts
        self._graph = graph
        self._ledger = ledger

    @staticmethod
    def _event(
        artifact: ReasoningArtifact,
        context: ArtifactEventContext,
        *,
        event_type: str,
        payload: dict[str, object],
    ) -> LedgerAppend:
        event_payload = dict(payload)
        attribution = artifact.metadata.get("attribution")
        if attribution is not None:
            event_payload["attribution"] = attribution
        evidence_disposition = artifact.metadata.get("evidence_disposition")
        if evidence_disposition is not None:
            event_payload["evidence_disposition"] = evidence_disposition
        return LedgerAppend(
            id=context.event_id,
            workspace_id=artifact.workspace_id,
            session_id=artifact.session_id,
            event_type=event_type,
            payload_schema_version=1,
            causation_id=context.causation_id,
            correlation_id=context.correlation_id,
            actor_class=context.actor_class,
            actor_id=context.actor_id,
            round=artifact.round,
            payload=event_payload,
            recorded_at=context.recorded_at,
        )

    @staticmethod
    def _node(artifact: ReasoningArtifact, *, node_id: UUID, label: str) -> GraphNode:
        return GraphNode(
            id=node_id,
            workspace_id=artifact.workspace_id,
            session_id=artifact.session_id,
            kind=artifact.kind,
            ref_id=artifact.id,
            label=label,
            attrs={"logical_id": str(artifact.logical_id), "version": artifact.version},
        )

    async def _relationship_targets(
        self, artifact: ReasoningArtifact, relationship_edge_ids: tuple[UUID, ...]
    ) -> tuple[tuple[UUID, GraphNode], ...]:
        if len(relationship_edge_ids) != len(artifact.parent_relationships):
            raise ArtifactCommitError("each parent relationship requires one edge id")
        targets: list[tuple[UUID, GraphNode]] = []
        for edge_id, relationship in zip(
            relationship_edge_ids, artifact.parent_relationships, strict=True
        ):
            if relationship.edge_type is GraphEdgeType.SUPERSEDES:
                raise ArtifactCommitError("SUPERSEDES is derived from the revision predecessor")
            target = await self._graph.node_for_artifact(
                artifact.workspace_id, artifact.session_id, relationship.target_artifact_id
            )
            if target is None:
                raise ArtifactCommitError(
                    f"parent artifact {relationship.target_artifact_id} has no graph projection"
                )
            targets.append((edge_id, target))
        return tuple(targets)

    async def _add_relationships(
        self,
        artifact: ReasoningArtifact,
        node: GraphNode,
        targets: tuple[tuple[UUID, GraphNode], ...],
        context: ArtifactEventContext,
    ) -> None:
        for relationship, (edge_id, target) in zip(
            artifact.parent_relationships, targets, strict=True
        ):
            qualifier: dict[str, object] = {}
            if relationship.edge_type is GraphEdgeType.ATTACKS and isinstance(
                artifact.payload, CritiquePayload
            ):
                qualifier = {
                    "type": artifact.payload.critique_type.value,
                    "severity": artifact.payload.severity.value,
                }
            await self._graph.add_edge(
                GraphEdge(
                    id=edge_id,
                    workspace_id=artifact.workspace_id,
                    session_id=artifact.session_id,
                    from_node=node.id,
                    to_node=target.id,
                    edge_type=relationship.edge_type,
                    qualifier=qualifier,
                    actor_class=context.actor_class,
                    actor_id=context.actor_id,
                )
            )

    async def commit(
        self,
        artifact: ReasoningArtifact,
        *,
        node_id: UUID,
        relationship_edge_ids: tuple[UUID, ...] = (),
        label: str,
        context: ArtifactEventContext,
    ) -> ArtifactWriteResult:
        """Insert an initial artifact, graph node, and ledger event."""
        if artifact.version != 1 or artifact.supersedes_id is not None:
            raise ArtifactCommitError("initial artifact commit requires version 1")
        if artifact.status is not LifecycleStatus.ACTIVE:
            raise ArtifactCommitError("initial artifact commit requires ACTIVE status")

        targets = await self._relationship_targets(artifact, relationship_edge_ids)
        await self._artifacts.add(artifact)
        node = self._node(artifact, node_id=node_id, label=label)
        await self._graph.add_node(node)
        await self._add_relationships(artifact, node, targets, context)
        event = await self._ledger.append(
            self._event(
                artifact,
                context,
                event_type="ARTIFACT_COMMITTED",
                payload={
                    "artifact_id": str(artifact.id),
                    "kind": artifact.kind.value,
                    "logical_id": str(artifact.logical_id),
                    "version": artifact.version,
                },
            )
        )
        return ArtifactWriteResult(artifact=artifact, event=event)

    async def revise(
        self,
        artifact: ReasoningArtifact,
        *,
        node_id: UUID,
        edge_id: UUID,
        relationship_edge_ids: tuple[UUID, ...] = (),
        label: str,
        reason: str,
        context: ArtifactEventContext,
    ) -> ArtifactWriteResult:
        """Append a revision, supersede its predecessor, and project their relationship."""
        if artifact.supersedes_id is None or artifact.version <= 1:
            raise ArtifactCommitError("revision requires a predecessor and version greater than 1")
        if artifact.status is not LifecycleStatus.ACTIVE:
            raise ArtifactCommitError("revision requires ACTIVE status")
        if not reason.strip():
            raise ArtifactCommitError("revision reason must not be blank")

        previous = await self._artifacts.get_for_update(
            artifact.workspace_id, artifact.session_id, artifact.supersedes_id
        )
        if previous is None:
            raise ArtifactCommitError(
                f"predecessor artifact {artifact.supersedes_id} does not exist"
            )
        if previous.status is not LifecycleStatus.ACTIVE:
            raise ArtifactCommitError("only an ACTIVE artifact may be revised")
        if (
            previous.logical_id != artifact.logical_id
            or previous.kind is not artifact.kind
            or previous.version + 1 != artifact.version
        ):
            raise ArtifactCommitError("revision must follow the same logical artifact and kind")

        previous_node = await self._graph.node_for_artifact(
            previous.workspace_id, previous.session_id, previous.id
        )
        if previous_node is None:
            raise ArtifactCommitError(f"predecessor artifact {previous.id} has no graph projection")
        targets = await self._relationship_targets(artifact, relationship_edge_ids)

        await self._artifacts.add(artifact)
        await self._artifacts.set_lifecycle(
            previous.workspace_id,
            previous.session_id,
            previous.id,
            LifecycleStatus.SUPERSEDED,
            updated_at=context.recorded_at,
        )
        next_node = self._node(artifact, node_id=node_id, label=label)
        await self._graph.add_node(next_node)
        await self._add_relationships(artifact, next_node, targets, context)
        await self._graph.add_edge(
            GraphEdge(
                id=edge_id,
                workspace_id=artifact.workspace_id,
                session_id=artifact.session_id,
                from_node=next_node.id,
                to_node=previous_node.id,
                edge_type=GraphEdgeType.SUPERSEDES,
                qualifier={"reason": reason},
                actor_class=context.actor_class,
                actor_id=context.actor_id,
            )
        )
        event = await self._ledger.append(
            self._event(
                artifact,
                context,
                event_type="ARTIFACT_REVISED",
                payload={
                    "artifact_id": str(artifact.id),
                    "kind": artifact.kind.value,
                    "logical_id": str(artifact.logical_id),
                    "supersedes_id": str(previous.id),
                    "version": artifact.version,
                    "reason": reason,
                },
            )
        )
        return ArtifactWriteResult(artifact=artifact, event=event)

    async def withdraw(
        self,
        workspace_id: UUID,
        session_id: UUID,
        artifact_id: UUID,
        *,
        reason: str,
        warrant_artifact_ids: tuple[UUID, ...],
        context: ArtifactEventContext,
    ) -> ArtifactWriteResult:
        """Additively withdraw one active artifact and record why."""
        if not reason.strip():
            raise ArtifactCommitError("withdrawal reason must not be blank")
        if not warrant_artifact_ids:
            raise ArtifactCommitError("withdrawal requires at least one warrant artifact id")
        if len(warrant_artifact_ids) != len(set(warrant_artifact_ids)):
            raise ArtifactCommitError("withdrawal warrant artifact ids must be unique")
        for warrant_id in warrant_artifact_ids:
            if await self._graph.node_for_artifact(workspace_id, session_id, warrant_id) is None:
                raise ArtifactCommitError(
                    f"withdrawal warrant artifact {warrant_id} has no graph projection"
                )
        artifact = await self._artifacts.get_for_update(workspace_id, session_id, artifact_id)
        if artifact is None:
            raise ArtifactCommitError(f"artifact {artifact_id} does not exist")
        if artifact.status is not LifecycleStatus.ACTIVE:
            raise ArtifactCommitError("only an ACTIVE artifact may be withdrawn")

        await self._artifacts.set_lifecycle(
            artifact.workspace_id,
            artifact.session_id,
            artifact.id,
            LifecycleStatus.WITHDRAWN,
            updated_at=context.recorded_at,
        )
        withdrawn = artifact.model_copy(
            update={"status": LifecycleStatus.WITHDRAWN, "updated_at": context.recorded_at}
        )
        event = await self._ledger.append(
            self._event(
                withdrawn,
                context,
                event_type="ARTIFACT_WITHDRAWN",
                payload={
                    "artifact_id": str(artifact.id),
                    "kind": artifact.kind.value,
                    "logical_id": str(artifact.logical_id),
                    "version": artifact.version,
                    "reason": reason,
                    "warrant_artifact_ids": [str(value) for value in warrant_artifact_ids],
                },
            )
        )
        return ArtifactWriteResult(artifact=withdrawn, event=event)
