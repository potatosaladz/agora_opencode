"""Infrastructure-free contracts for stateless logical-agent reasoning."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "AgentRuntime",
    "AuthorizedKnowledge",
    "AuthorizedKnowledgeChunk",
    "ContextArtifact",
    "PinnedAgentDefinition",
    "ProposalLike",
    "ReasoningContext",
    "ReasoningPhase",
    "ReasoningStrategy",
    "TurnExecutionResult",
]


# trace: FR-209
class ReasoningPhase(StrEnum):
    ASSESS = "ASSESS"
    DECOMPOSE = "DECOMPOSE"
    ARGUE = "ARGUE"
    CRITIQUE = "CRITIQUE"
    REVISE = "REVISE"
    SCORE = "SCORE"


class AuthorizedKnowledgeChunk(BaseModel):
    """One pre-authorized retrieval hit with exact provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    namespace_id: UUID
    chunk_id: UUID
    document_id: UUID
    source_id: UUID
    citation: str = Field(min_length=1)
    text: str
    source_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    locator_json: str = Field(min_length=2)
    chunker_version: str = Field(min_length=1)
    source_timestamp: datetime
    document_timestamp: datetime
    retrieved_at: datetime
    trust_level: str = Field(min_length=1)
    lexical_score: float | None = None
    vector_score: float | None = None
    fused_score: float = Field(ge=0)
    rerank_score: float | None = None
    index_version: str = Field(min_length=1)


class AuthorizedKnowledge(BaseModel):
    """Explicit retrieval outcome; empty chunks mean successful no-match, never failure."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    query_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    requested_namespace_ids: tuple[UUID, ...]
    searched_namespace_ids: tuple[UUID, ...]
    index_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_version: str = Field(min_length=1)
    reranker_version: str = Field(min_length=1)
    lexical_count: int = Field(ge=0)
    vector_count: int = Field(ge=0)
    degradation: str = Field(min_length=1)
    warnings: tuple[str, ...] = ()
    chunks: tuple[AuthorizedKnowledgeChunk, ...]


class ContextArtifact(BaseModel):
    """Validated eligible artifact snapshot for one turn."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    kind: str = Field(min_length=1)
    owner_actor_class: str = Field(min_length=1)
    owner_actor_id: UUID
    round: int = Field(ge=0)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    artifact_json: str = Field(min_length=2)


class PinnedAgentDefinition(BaseModel):
    """Immutable declarative definition fields available to one logical turn."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    logical_id: UUID
    version: int = Field(gt=0)
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    role_kind: str = Field(min_length=1)
    objectives: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    knowledge_namespace_ids: tuple[UUID, ...] = ()
    strategy_name: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    prompt_ref: str = Field(min_length=1)
    prompt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator(
        "name",
        "domain",
        "objectives",
        "constraints",
        "strategy_name",
        "strategy_version",
        "prompt_ref",
    )
    @classmethod
    def definition_text_not_blank(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        values = (value,) if isinstance(value, str) else value
        if any(not item.strip() for item in values):
            raise ValueError("pinned agent definition text must not be blank")
        return value


class ReasoningContext(BaseModel):
    """Complete immutable context supplied by coordinator to one logical agent."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    workspace_id: UUID
    session_id: UUID
    agent_definition_id: UUID
    agent_definition_version: int = Field(gt=0)
    agent_definition: PinnedAgentDefinition
    strategy_name: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    canonicalizer_version: str = Field(min_length=1)
    turn_id: UUID
    correlation_id: UUID
    causation_id: UUID
    round: int = Field(ge=1)
    phase: ReasoningPhase
    problem_statement: str = Field(min_length=1)
    objective_summaries: tuple[str, ...] = ()
    constraint_summaries: tuple[str, ...] = ()
    visible_artifact_ids: tuple[UUID, ...] = ()
    visible_artifacts: tuple[ContextArtifact, ...] = ()
    retrieval: AuthorizedKnowledge | None = None
    sealed: bool
    budget_remaining_tokens: int = Field(gt=0)
    budget_remaining_usd: Decimal = Field(ge=0)
    timeout_s: float = Field(gt=0)
    schema_version: int = 1

    @field_validator(
        "strategy_name",
        "strategy_version",
        "canonicalizer_version",
        "problem_statement",
        "objective_summaries",
        "constraint_summaries",
    )
    @classmethod
    def text_not_blank(cls, value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        values = (value,) if isinstance(value, str) else value
        if any(not item.strip() for item in values):
            raise ValueError("reasoning context text must not be blank")
        return value

    @model_validator(mode="after")
    def protocol_invariants(self) -> ReasoningContext:
        if self.schema_version != 1:
            raise ValueError("unsupported ReasoningContext schema_version")
        if (
            self.agent_definition.id != self.agent_definition_id
            or self.agent_definition.version != self.agent_definition_version
            or self.agent_definition.strategy_name != self.strategy_name
            or self.agent_definition.strategy_version != self.strategy_version
        ):
            raise ValueError("reasoning context does not match pinned agent definition")
        artifact_ids = tuple(artifact.id for artifact in self.visible_artifacts)
        if artifact_ids != self.visible_artifact_ids or len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("visible artifact IDs must exactly match unique hydrated artifacts")
        if (
            self.round == 1
            and self.phase is ReasoningPhase.ASSESS
            and (not self.sealed or self.visible_artifacts)
        ):
            raise ValueError("round 1 ASSESS must be sealed from other agents")
        return self


@runtime_checkable
class ProposalLike(Protocol):
    """Minimum identity shared by all versioned proposal bundle contracts."""

    @property
    def turn_id(self) -> UUID: ...


class TurnExecutionResult[ProposalT](BaseModel):
    """Proposal plus optional nondeterministic provider attribution.

    Deterministic strategies have no provider call to attribute and therefore carry no
    provider/model/raw reference and zero accounting. Activity-backed strategies must carry
    the complete provider tuple; partial attribution is rejected.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    proposal: ProposalT
    provider: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal(0), ge=0)
    raw_artifact_ref: str | None = Field(default=None, pattern=r"^.+/.+#sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def complete_attribution(self) -> TurnExecutionResult[ProposalT]:
        provider_values = (self.provider, self.model, self.raw_artifact_ref)
        if any(value is not None for value in provider_values) and not all(
            value is not None for value in provider_values
        ):
            raise ValueError("provider execution attribution must be complete")
        if self.provider is None and (
            self.input_tokens != 0 or self.output_tokens != 0 or self.cost_usd != 0
        ):
            raise ValueError("metadata-free deterministic execution must have zero accounting")
        return self


@runtime_checkable
class ReasoningStrategy[ProposalT_co: ProposalLike](Protocol):
    name: str
    version: str

    async def propose(
        self, context: ReasoningContext
    ) -> ProposalT_co | TurnExecutionResult[ProposalT_co]: ...


@runtime_checkable
class AgentRuntime[ProposalT_co: ProposalLike](Protocol):
    async def run_turn(self, context: ReasoningContext) -> TurnExecutionResult[ProposalT_co]: ...
