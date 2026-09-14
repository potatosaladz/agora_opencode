"""Fail-closed assembly of one agent's complete authorized reasoning context."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.agent_registry import AgentDefinition, AgentRegistry, AgentStatus
from app.domain.coordinator_policy import EffectiveMembershipStore
from app.domain.knowledge import NamespaceSubjectKind
from app.domain.phase3_api import Phase3ArtifactStore, Phase3SessionStore
from app.domain.reasoning import (
    ConstraintArtifact,
    LifecycleStatus,
    ObjectiveArtifact,
    ReasoningArtifact,
)
from app.domain.retrieval import PrincipalClass, RetrievalRequest, RetrievalResult, Retriever
from app.domain.session_binding import (
    ConstraintBinding,
    ObjectiveBinding,
)
from app.ports.agent_runtime import (
    AuthorizedKnowledge,
    AuthorizedKnowledgeChunk,
    ContextArtifact,
    PinnedAgentDefinition,
    ReasoningContext,
    ReasoningPhase,
)
from app.ports.errors import PermanentPortError

__all__ = ["ReasoningContextAssembler", "ReasoningContextRequest"]


# trace: FR-209
class ReasoningContextRequest(BaseModel):
    """Coordinator-owned inputs that cannot be derived from durable session state."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    workspace_id: UUID
    session_id: UUID
    agent_definition_id: UUID
    turn_id: UUID
    correlation_id: UUID
    causation_id: UUID
    round: int = Field(ge=1)
    phase: ReasoningPhase
    canonicalizer_version: str = Field(min_length=1)
    visible_artifact_ids: tuple[UUID, ...] = ()
    retrieval_request: RetrievalRequest | None = None
    budget_remaining_tokens: int = Field(gt=0)
    budget_remaining_usd: Decimal = Field(ge=0)
    timeout_s: float = Field(gt=0)


class ReasoningContextAssembler:
    """Hydrate and authorize immutable turn inputs without granting write authority."""

    def __init__(
        self,
        sessions: Phase3SessionStore,
        artifacts: Phase3ArtifactStore,
        registry: AgentRegistry,
        retriever: Retriever,
        memberships: EffectiveMembershipStore,
    ) -> None:
        self._sessions = sessions
        self._artifacts = artifacts
        self._registry = registry
        self._retriever = retriever
        self._memberships = memberships

    async def assemble(self, request: ReasoningContextRequest) -> ReasoningContext:
        session = await self._sessions.get(request.workspace_id, request.session_id)
        if (
            session is None
            or session.workspace_id != request.workspace_id
            or session.id != request.session_id
        ):
            raise PermanentPortError(
                "bound reasoning session does not exist", port="reasoning_context"
            )

        membership = await self._memberships.membership(
            request.workspace_id, request.session_id, round=request.round
        )
        effective_definition = next(
            (item for item in membership.definitions if item.id == request.agent_definition_id),
            None,
        )
        if effective_definition is None:
            raise PermanentPortError(
                "agent definition is not pinned to the reasoning session",
                port="reasoning_context",
            )
        definition = await self._registry.get_definition(request.agent_definition_id)
        if (
            definition is None
            or definition != effective_definition
            or definition.workspace_id != request.workspace_id
        ):
            raise PermanentPortError(
                "pinned agent definition identity or version does not resolve",
                port="reasoning_context",
            )
        if definition.status in {AgentStatus.DRAFT, AgentStatus.WITHDRAWN}:
            raise PermanentPortError(
                "pinned agent definition is not runnable", port="reasoning_context"
            )

        sealed_assessment = request.round == 1 and request.phase is ReasoningPhase.ASSESS
        if sealed_assessment and request.visible_artifact_ids:
            raise PermanentPortError(
                "round 1 ASSESS cannot include prior agent artifacts",
                port="reasoning_context",
            )
        if len(set(request.visible_artifact_ids)) != len(request.visible_artifact_ids):
            raise PermanentPortError(
                "visible artifact IDs must be unique", port="reasoning_context"
            )

        objectives = await self._load_objectives(request, session.objectives)
        constraints = await self._load_constraints(request, session.constraints)
        visible_artifacts = await self._load_visible_artifacts(request)
        retrieval = await self._retrieve(request, definition)
        pinned_snapshot = _pinned_definition(definition)

        return ReasoningContext(
            workspace_id=request.workspace_id,
            session_id=request.session_id,
            agent_definition_id=definition.id,
            agent_definition_version=definition.version,
            agent_definition=pinned_snapshot,
            strategy_name=definition.strategy_ref,
            strategy_version=definition.strategy_ver,
            canonicalizer_version=request.canonicalizer_version,
            turn_id=request.turn_id,
            correlation_id=request.correlation_id,
            causation_id=request.causation_id,
            round=request.round,
            phase=request.phase,
            problem_statement=session.problem_statement,
            objective_summaries=objectives,
            constraint_summaries=constraints,
            visible_artifact_ids=tuple(artifact.id for artifact in visible_artifacts),
            visible_artifacts=visible_artifacts,
            retrieval=retrieval,
            sealed=sealed_assessment,
            budget_remaining_tokens=request.budget_remaining_tokens,
            budget_remaining_usd=request.budget_remaining_usd,
            timeout_s=request.timeout_s,
        )

    async def _load_objectives(
        self, request: ReasoningContextRequest, bindings: tuple[ObjectiveBinding, ...]
    ) -> tuple[str, ...]:
        summaries: list[str] = []
        for binding in bindings:
            artifact = await self._artifacts.get(
                request.workspace_id, binding.artifact_id, session_id=request.session_id
            )
            if (
                not isinstance(artifact, ObjectiveArtifact)
                or artifact.workspace_id != request.workspace_id
                or artifact.session_id != request.session_id
                or artifact.status is not LifecycleStatus.ACTIVE
            ):
                raise PermanentPortError(
                    "bound objective is unavailable or ineligible", port="reasoning_context"
                )
            summaries.append(_json(artifact.payload.model_dump(mode="json")))
        return tuple(summaries)

    async def _load_constraints(
        self, request: ReasoningContextRequest, bindings: tuple[ConstraintBinding, ...]
    ) -> tuple[str, ...]:
        summaries: list[str] = []
        for binding in bindings:
            artifact = await self._artifacts.get(
                request.workspace_id, binding.artifact_id, session_id=request.session_id
            )
            if not isinstance(artifact, ConstraintArtifact) or (
                artifact.workspace_id != request.workspace_id
                or artifact.session_id != request.session_id
                or artifact.status is not LifecycleStatus.ACTIVE
            ):
                raise PermanentPortError(
                    "bound constraint is unavailable or ineligible", port="reasoning_context"
                )
            summaries.append(_json(artifact.payload.model_dump(mode="json")))
        return tuple(summaries)

    async def _load_visible_artifacts(
        self, request: ReasoningContextRequest
    ) -> tuple[ContextArtifact, ...]:
        snapshots: list[ContextArtifact] = []
        for artifact_id in request.visible_artifact_ids:
            artifact = await self._artifacts.get(
                request.workspace_id, artifact_id, session_id=request.session_id
            )
            if (
                artifact is None
                or artifact.workspace_id != request.workspace_id
                or artifact.session_id != request.session_id
                or artifact.status is not LifecycleStatus.ACTIVE
                or artifact.round > request.round
            ):
                raise PermanentPortError(
                    "visible artifact is unavailable or ineligible", port="reasoning_context"
                )
            snapshots.append(_artifact_snapshot(artifact))
        return tuple(snapshots)

    async def _retrieve(
        self, request: ReasoningContextRequest, definition: AgentDefinition
    ) -> AuthorizedKnowledge | None:
        retrieval_request = request.retrieval_request
        if retrieval_request is None:
            if definition.knowledge_ns:
                raise PermanentPortError(
                    "pinned agent knowledge requires an explicit retrieval request",
                    port="reasoning_context",
                )
            return None
        _validate_retrieval_request(request, definition, retrieval_request)
        result = await self._retriever.retrieve(retrieval_request)
        _validate_retrieval_result(definition, retrieval_request, result)
        return _authorized_knowledge(result)


def _pinned_definition(definition: AgentDefinition) -> PinnedAgentDefinition:
    return PinnedAgentDefinition(
        id=definition.id,
        logical_id=definition.logical_id,
        version=definition.version,
        name=definition.name,
        domain=definition.domain,
        role_kind=definition.role_kind.value,
        objectives=definition.objectives,
        constraints=definition.constraints,
        knowledge_namespace_ids=definition.knowledge_ns,
        strategy_name=definition.strategy_ref,
        strategy_version=definition.strategy_ver,
        prompt_ref=definition.prompt_ref,
        prompt_hash=definition.prompt_hash,
    )


def _validate_retrieval_request(
    request: ReasoningContextRequest,
    definition: AgentDefinition,
    retrieval: RetrievalRequest,
) -> None:
    expected_subjects = {
        (NamespaceSubjectKind.WORKSPACE, request.workspace_id),
        (NamespaceSubjectKind.AGENT_DEFINITION, definition.id),
        (NamespaceSubjectKind.SESSION, request.session_id),
    }
    actual_subjects = {(subject.kind, subject.id) for subject in retrieval.subjects}
    if (
        retrieval.workspace_id != request.workspace_id
        or retrieval.principal_class is not PrincipalClass.AGENT
        or retrieval.principal_id != definition.id
        or actual_subjects != expected_subjects
        or not set(retrieval.namespace_ids) <= set(definition.knowledge_ns)
        or retrieval.trace_id != request.correlation_id
    ):
        raise PermanentPortError(
            "retrieval request is not scoped to the pinned session agent",
            port="reasoning_context",
        )


def _validate_retrieval_result(
    definition: AgentDefinition, request: RetrievalRequest, result: RetrievalResult
) -> None:
    searched = set(result.searched_namespace_ids)
    chunk_ids = tuple(chunk.chunk_id for chunk in result.chunks)
    expected_query_hash = "sha256:" + hashlib.sha256(request.query.encode()).hexdigest()
    if (
        result.query_hash != expected_query_hash
        or result.requested_namespace_ids != request.namespace_ids
        or len(searched) != len(result.searched_namespace_ids)
        or not searched <= set(request.namespace_ids)
        or not searched <= set(definition.knowledge_ns)
        or result.index_version != request.index_version
        or result.embedding_model != request.embedding_model
        or result.embedding_version != request.embedding_version
        or len(set(chunk_ids)) != len(chunk_ids)
        or any(chunk.namespace_id not in searched for chunk in result.chunks)
        or any(chunk.index_version != result.index_version for chunk in result.chunks)
    ):
        raise PermanentPortError(
            "retrieval result does not match the authorized request", port="reasoning_context"
        )


def _authorized_knowledge(result: RetrievalResult) -> AuthorizedKnowledge:
    return AuthorizedKnowledge(
        query_hash=result.query_hash,
        requested_namespace_ids=result.requested_namespace_ids,
        searched_namespace_ids=result.searched_namespace_ids,
        index_version=result.index_version,
        embedding_model=result.embedding_model,
        embedding_version=result.embedding_version,
        reranker_version=result.reranker_version,
        lexical_count=result.lexical_count,
        vector_count=result.vector_count,
        degradation=result.degradation.value,
        warnings=result.warnings,
        chunks=tuple(
            AuthorizedKnowledgeChunk(
                namespace_id=chunk.namespace_id,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                source_id=chunk.source_id,
                citation=chunk.citation,
                text=chunk.text,
                source_content_hash=chunk.source_content_hash,
                content_hash=chunk.content_hash,
                locator_json=_json(chunk.locator),
                chunker_version=chunk.chunker_version,
                source_timestamp=chunk.source_timestamp,
                document_timestamp=chunk.document_timestamp,
                retrieved_at=chunk.retrieved_at,
                trust_level=chunk.trust_level,
                lexical_score=chunk.lexical_score,
                vector_score=chunk.vector_score,
                fused_score=chunk.fused_score,
                rerank_score=chunk.rerank_score,
                index_version=chunk.index_version,
            )
            for chunk in result.chunks
        ),
    )


def _artifact_snapshot(artifact: ReasoningArtifact) -> ContextArtifact:
    return ContextArtifact(
        id=artifact.id,
        kind=artifact.kind.value,
        owner_actor_class=artifact.owner_actor_class.value,
        owner_actor_id=artifact.owner_actor_id,
        round=artifact.round,
        content_hash=artifact.content_hash,
        artifact_json=_json(artifact.model_dump(mode="json")),
    )


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
