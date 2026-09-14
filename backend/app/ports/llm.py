"""Provider-neutral LLM contracts — ``docs/PORTS.md`` §1 and ADR-006."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.ports.health import HealthStatus
from app.ports.storage import ObjectRef, SecretRef

__all__ = [
    "EmbeddingResponse",
    "FinishReason",
    "LLMCallTrace",
    "LLMMessage",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "MessageRole",
    "ProviderCapabilities",
    "TokenUsage",
]


class MessageRole(StrEnum):
    """Roles accepted by the provider-neutral chat contract."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class FinishReason(StrEnum):
    """Normalized generation stop reasons."""

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    TOOL_CALL = "tool_call"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """One validated conversation turn."""

    role: MessageRole
    content: str

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("LLM message content must not be empty")


@dataclass(frozen=True, slots=True)
class LLMCallTrace:
    """Stable identifiers attached to provider spans and raw artifacts."""

    correlation_id: str
    session_id: str | None = None
    agent_id: str | None = None
    code_version: str = "dev"

    def __post_init__(self) -> None:
        if not self.correlation_id:
            raise ValueError("correlation_id is required")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Normalized token counts and the call-time USD cost estimate."""

    input_tokens: int = 0
    output_tokens: int = 0
    embedding_tokens: int = 0
    cost_usd: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.embedding_tokens) < 0:
            raise ValueError("token counts must not be negative")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must not be negative")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.embedding_tokens


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Capabilities are declared by an adapter and never inferred by callers."""

    structured_output: bool = False
    deterministic: bool = False
    max_context_tokens: int = 4096
    supports_tools: bool = False
    embedding_models: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_context_tokens <= 0:
            raise ValueError("max_context_tokens must be positive")


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """One generation request, including trace and credential references."""

    messages: tuple[LLMMessage, ...]
    model: str
    trace: LLMCallTrace
    secret_ref: SecretRef
    response_schema: type[BaseModel] | None = field(default=None, compare=False)
    temperature: float = 0.0
    max_output_tokens: int = 1024
    stop: tuple[str, ...] = ()
    timeout_s: float = 30.0
    seed: int | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("at least one LLM message is required")
        if not self.model:
            raise ValueError("model is required")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.schema_version != 1:
            raise ValueError("unsupported LLMRequest schema_version")


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized generation result and its reproducibility artifact."""

    text: str
    parsed: BaseModel | None
    finish_reason: FinishReason
    usage: TokenUsage
    model: str
    provider: str
    latency_ms: int
    raw_artifact_ref: ObjectRef
    retry_attempts: int = 0
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.latency_ms < 0 or self.retry_attempts < 0:
            raise ValueError("latency and retry counts must not be negative")
        if not self.raw_artifact_ref.digest:
            raise ValueError("raw_artifact_ref must be content-addressed")
        if self.schema_version != 1:
            raise ValueError("unsupported LLMResponse schema_version")


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    """Normalized embedding result."""

    embeddings: tuple[tuple[float, ...], ...]
    model: str
    usage: TokenUsage
    raw_artifact_ref: ObjectRef
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.embeddings or any(not vector for vector in self.embeddings):
            raise ValueError("embedding response must contain non-empty vectors")
        if not self.raw_artifact_ref.digest:
            raise ValueError("raw_artifact_ref must be content-addressed")
        if self.schema_version != 1:
            raise ValueError("unsupported EmbeddingResponse schema_version")


@runtime_checkable
class LLMProvider(Protocol):
    """Generation and embedding behind the platform's provider boundary."""

    async def generate(self, request: LLMRequest) -> LLMResponse: ...

    async def embed(
        self, inputs: Sequence[str], *, model: str, secret_ref: SecretRef
    ) -> EmbeddingResponse: ...

    async def capabilities(self) -> ProviderCapabilities: ...

    async def health(self) -> HealthStatus: ...

    async def close(self) -> None: ...
