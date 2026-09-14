"""Versioned, deterministic retrieval-mechanics baseline evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "BaselineCorpus",
    "BaselineMetrics",
    "BaselineQuery",
    "BaselineQueryResult",
    "BaselineSource",
    "BaselineSourceChunk",
    "evaluate_baseline",
]


# trace: FR-404
class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class BaselineQuery(_FrozenModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    relevant_chunk_ids: tuple[UUID, ...] = Field(min_length=1)
    expected_retrieved_chunk_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("id", "text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("baseline query strings must not be blank")
        return value

    @model_validator(mode="after")
    def _unique_labels(self) -> BaselineQuery:
        for name, values in (
            ("relevant_chunk_ids", self.relevant_chunk_ids),
            ("expected_retrieved_chunk_ids", self.expected_retrieved_chunk_ids),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must be unique")
        return self


class BaselineSourceChunk(_FrozenModel):
    id: UUID
    text: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    vector_axis: int = Field(ge=0, lt=1536)

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("baseline chunk text must not be blank")
        return value


class BaselineSource(_FrozenModel):
    id: UUID
    document_id: UUID
    namespace: str = Field(pattern=r"^(AUTHORIZED|UNAUTHORIZED)$")
    status: str = Field(pattern=r"^(READY|RETRACTED)$")
    title: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    chunks: tuple[BaselineSourceChunk, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_chunks(self) -> BaselineSource:
        ids = [chunk.id for chunk in self.chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("source chunk ids must be unique")
        return self


class BaselineCorpus(_FrozenModel):
    corpus_version: str = Field(min_length=1)
    label_version: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    chunker_version: str = Field(min_length=1)
    index_version: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_version: str = Field(min_length=1)
    reranker_version: str = Field(min_length=1)
    final_k: int = Field(ge=1, le=100)
    caveats: tuple[str, ...] = Field(min_length=1)
    sources: tuple[BaselineSource, ...] = Field(min_length=1)
    queries: tuple[BaselineQuery, ...] = Field(min_length=1)

    @field_validator(
        "corpus_version",
        "label_version",
        "parser_version",
        "chunker_version",
        "index_version",
        "embedding_model",
        "embedding_version",
        "reranker_version",
    )
    @classmethod
    def _version_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("baseline versions must not be blank")
        return value

    @field_validator("caveats")
    @classmethod
    def _caveats_not_blank(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not caveat.strip() for caveat in value):
            raise ValueError("baseline caveats must not be blank")
        return value

    @model_validator(mode="after")
    def _unique_queries(self) -> BaselineCorpus:
        query_ids = [query.id for query in self.queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("baseline query ids must be unique")
        chunk_ids = [chunk.id for source in self.sources for chunk in source.chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("baseline chunk ids must be globally unique")
        known_ids = set(chunk_ids)
        for query in self.queries:
            if not set(query.relevant_chunk_ids) <= known_ids:
                raise ValueError("relevant_chunk_ids must resolve inside the baseline corpus")
            if not set(query.expected_retrieved_chunk_ids) <= known_ids:
                raise ValueError(
                    "expected_retrieved_chunk_ids must resolve inside the baseline corpus"
                )
            if len(query.expected_retrieved_chunk_ids) > self.final_k:
                raise ValueError("expected retrieval count cannot exceed final_k")
        return self


class BaselineQueryResult(_FrozenModel):
    query_id: str
    retrieved_chunk_ids: tuple[UUID, ...]
    relevant_retrieved: int = Field(ge=0)
    relevant_total: int = Field(ge=1)
    recall_proxy: float = Field(ge=0.0, le=1.0)
    precision_at_k: float = Field(ge=0.0, le=1.0)


class BaselineMetrics(_FrozenModel):
    corpus_version: str
    label_version: str
    query_results: tuple[BaselineQueryResult, ...]
    recall_proxy: float = Field(ge=0.0, le=1.0)
    precision_at_k: float = Field(ge=0.0, le=1.0)


def evaluate_baseline(
    corpus: BaselineCorpus, retrieved: Mapping[str, Sequence[UUID]]
) -> BaselineMetrics:
    """Score fixed reviewed labels; this is not open-world ground-truth recall."""
    expected = {query.id for query in corpus.queries}
    if set(retrieved) != expected:
        raise ValueError("retrieved query ids must exactly match the baseline corpus")

    results: list[BaselineQueryResult] = []
    for query in corpus.queries:
        hit_ids = tuple(retrieved[query.id])
        if len(hit_ids) != len(set(hit_ids)):
            raise ValueError(f"retrieved chunk ids must be unique for query {query.id}")
        if len(hit_ids) > corpus.final_k:
            raise ValueError(f"retrieved chunk count exceeds final_k for query {query.id}")
        relevant_count = len(set(hit_ids) & set(query.relevant_chunk_ids))
        results.append(
            BaselineQueryResult(
                query_id=query.id,
                retrieved_chunk_ids=hit_ids,
                relevant_retrieved=relevant_count,
                relevant_total=len(query.relevant_chunk_ids),
                recall_proxy=relevant_count / len(query.relevant_chunk_ids),
                precision_at_k=relevant_count / corpus.final_k,
            )
        )

    return BaselineMetrics(
        corpus_version=corpus.corpus_version,
        label_version=corpus.label_version,
        query_results=tuple(results),
        recall_proxy=sum(result.recall_proxy for result in results) / len(results),
        precision_at_k=sum(result.precision_at_k for result in results) / len(results),
    )
