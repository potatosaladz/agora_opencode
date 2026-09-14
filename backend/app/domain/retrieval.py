"""Strict hybrid retrieval values and replaceable retrieval ports."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.knowledge import JsonObject, NamespaceSubjectKind
from app.ports.errors import PermanentPortError

__all__ = [
    "CandidateSearch",
    "HybridCandidate",
    "IndexMismatchError",
    "PrincipalClass",
    "Reranker",
    "RetrievalAttempt",
    "RetrievalAudit",
    "RetrievalDegradation",
    "RetrievalOutcome",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalSubject",
    "RetrievedChunk",
    "Retriever",
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class RetrievalDegradation(StrEnum):
    NONE = "NONE"
    LEXICAL_ONLY = "LEXICAL_ONLY"
    INDEX_MISMATCH = "INDEX_MISMATCH"
    RERANKER_FAILED = "RERANKER_FAILED"


class PrincipalClass(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"


class RetrievalOutcome(StrEnum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    RAG_FAILED = "RAG_FAILED"


class IndexMismatchError(PermanentPortError):
    """Requested embedding identity does not match an authorized namespace index."""


class RetrievalSubject(_FrozenModel):
    kind: NamespaceSubjectKind
    id: UUID


class RetrievalRequest(_FrozenModel):
    attempt_id: UUID
    trace_id: UUID
    workspace_id: UUID
    principal_class: PrincipalClass
    principal_id: UUID
    namespace_ids: tuple[UUID, ...] = Field(min_length=1)
    subjects: tuple[RetrievalSubject, ...] = Field(min_length=1)
    query: str = Field(min_length=1)
    query_vector: Sequence[float]
    embedding_model: str = Field(min_length=1)
    embedding_version: str = Field(min_length=1)
    index_version: str = Field(min_length=1)
    requested_at: datetime
    expected_match: bool = False
    final_k: int = Field(default=8, ge=1, le=100)
    lexical_min_score: float = Field(default=0.0, ge=0.0)
    vector_min_score: float = Field(default=0.0, ge=-1.0, le=1.0)

    @field_validator("query", "embedding_model", "embedding_version", "index_version")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("retrieval strings must not be blank")
        return value

    @field_validator("requested_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must include an RFC 3339 offset")
        return value.astimezone(UTC)

    @field_validator("query_vector")
    @classmethod
    def _finite_vector(cls, value: Sequence[float]) -> Sequence[float]:
        if not value or not all(isfinite(item) for item in value):
            raise ValueError("query_vector must contain finite values")
        return value

    @model_validator(mode="after")
    def _unique_scope(self) -> RetrievalRequest:
        if len(set(self.namespace_ids)) != len(self.namespace_ids):
            raise ValueError("namespace_ids must be unique")
        identities = {(subject.kind, subject.id) for subject in self.subjects}
        if len(identities) != len(self.subjects):
            raise ValueError("subjects must be unique")
        if (NamespaceSubjectKind.WORKSPACE, self.workspace_id) not in identities:
            raise ValueError("subjects must include the request workspace")
        principal_kind = (
            NamespaceSubjectKind.USER
            if self.principal_class is PrincipalClass.HUMAN
            else NamespaceSubjectKind.AGENT_DEFINITION
        )
        if (principal_kind, self.principal_id) not in identities:
            raise ValueError("subjects must include the typed principal identity")
        return self


class RetrievalAttempt(_FrozenModel):
    attempt_id: UUID
    trace_id: UUID
    workspace_id: UUID
    principal_class: PrincipalClass
    principal_id: UUID
    requested_at: datetime
    completed_at: datetime
    query_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    requested_namespace_ids: tuple[UUID, ...]
    searched_namespace_ids: tuple[UUID, ...]
    result_chunk_ids: tuple[UUID, ...]
    result_content_hashes: tuple[str, ...]
    index_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_version: str = Field(min_length=1)
    reranker_version: str | None = None
    lexical_count: int = Field(ge=0)
    vector_count: int = Field(ge=0)
    result_count: int = Field(ge=0)
    outcome: RetrievalOutcome
    degradation: RetrievalDegradation | None = None
    warnings: tuple[str, ...] = ()

    @field_validator("requested_at", "completed_at")
    @classmethod
    def _attempt_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit timestamps must include an RFC 3339 offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _census_matches_outcome(self) -> RetrievalAttempt:
        if self.result_count != len(self.result_chunk_ids):
            raise ValueError("result_count must match result_chunk_ids")
        if self.result_count != len(self.result_content_hashes):
            raise ValueError("result_count must match result_content_hashes")
        if any(not _valid_sha256(value) for value in self.result_content_hashes):
            raise ValueError("result_content_hashes must contain sha256 digests")
        if self.outcome is RetrievalOutcome.DENIED and (
            self.searched_namespace_ids
            or self.result_chunk_ids
            or self.result_content_hashes
            or self.lexical_count
            or self.vector_count
            or self.degradation is not None
        ):
            raise ValueError("denied attempts must have an empty result census")
        if self.outcome is RetrievalOutcome.ALLOWED and self.degradation is None:
            raise ValueError("allowed attempts require degradation metadata")
        if self.outcome is RetrievalOutcome.RAG_FAILED and (
            self.result_chunk_ids or self.result_content_hashes or self.result_count
        ):
            raise ValueError("failed retrieval attempts cannot contain results")
        return self


@runtime_checkable
class RetrievalAudit(Protocol):
    async def append(self, attempt: RetrievalAttempt) -> None: ...


def _valid_sha256(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


class HybridCandidate(_FrozenModel):
    namespace_id: UUID
    chunk_id: UUID
    document_id: UUID
    source_id: UUID
    citation: str = Field(min_length=1)
    text: str
    source_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    locator: JsonObject
    chunker_version: str
    source_timestamp: datetime
    document_timestamp: datetime
    retrieved_at: datetime
    trust_level: str
    score: float

    @field_validator("source_timestamp", "document_timestamp", "retrieved_at")
    @classmethod
    def _provenance_timestamp_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provenance timestamps must include an RFC 3339 offset")
        return value.astimezone(UTC)

    @field_validator("citation", "chunker_version", "trust_level")
    @classmethod
    def _provenance_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("citation provenance must not be blank")
        return value

    @field_validator("locator")
    @classmethod
    def _locator_not_empty(cls, value: JsonObject) -> JsonObject:
        start, end = value.get("char_start"), value.get("char_end")
        if not isinstance(start, int) or isinstance(start, bool) or start < 0:
            raise ValueError("locator char_start must be a nonnegative integer")
        if not isinstance(end, int) or isinstance(end, bool) or end <= start:
            raise ValueError("locator char_end must be greater than char_start")
        return value


class RetrievedChunk(HybridCandidate):
    lexical_score: float | None = None
    vector_score: float | None = None
    fused_score: float = Field(ge=0.0)
    rerank_score: float | None = None
    index_version: str


class RetrievalResult(_FrozenModel):
    query_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    requested_namespace_ids: tuple[UUID, ...]
    searched_namespace_ids: tuple[UUID, ...]
    index_version: str
    embedding_model: str
    embedding_version: str
    reranker_version: str
    lexical_count: int = Field(ge=0)
    vector_count: int = Field(ge=0)
    degradation: RetrievalDegradation
    warnings: tuple[str, ...] = ()
    chunks: tuple[RetrievedChunk, ...]


@runtime_checkable
class Retriever(Protocol):
    """Authorized retrieval composition boundary."""

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult: ...


@runtime_checkable
class CandidateSearch(Protocol):
    async def authorize(self, request: RetrievalRequest) -> tuple[UUID, ...]: ...

    async def lexical(self, request: RetrievalRequest, *, k: int) -> Sequence[HybridCandidate]: ...

    async def vector(self, request: RetrievalRequest, *, k: int) -> Sequence[HybridCandidate]: ...


@runtime_checkable
class Reranker(Protocol):
    version: str

    async def rerank(
        self, query: str, candidates: Sequence[RetrievedChunk], *, k: int
    ) -> Sequence[RetrievedChunk]: ...
