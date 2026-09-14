"""Deterministic fixture-driven ``LLMProvider`` used by tests and strict replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.adapters.llm.structured import parse_structured
from app.ports.errors import PermanentPortError
from app.ports.health import HealthStatus
from app.ports.llm import (
    EmbeddingResponse,
    FinishReason,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderCapabilities,
    TokenUsage,
)
from app.ports.storage import ObjectRef, ObjectStore, SecretRef

__all__ = ["MockLLMProvider", "MockScenario"]


@dataclass(frozen=True, slots=True)
class MockScenario:
    """All deterministic outputs for one fixture model.

    The first response is the normal completion. Later responses are bounded schema-repair
    completions; the sequence is restarted for every call, so replay does not depend on
    mutable process state.
    """

    responses: tuple[str, ...]
    input_tokens: int = 1
    output_tokens: int = 1
    cost_usd: Decimal = Decimal("0")
    finish_reason: FinishReason = FinishReason.STOP
    embeddings: tuple[tuple[float, ...], ...] = ()

    def __post_init__(self) -> None:
        if not self.responses:
            raise ValueError("a mock scenario requires at least one response")


class MockLLMProvider:
    """Offline provider with deterministic fixtures and content-addressed raw artifacts."""

    def __init__(
        self,
        object_store: ObjectStore,
        scenarios: Mapping[str, MockScenario],
        *,
        artifact_bucket: str = "llm-traces",
        max_repair_attempts: int = 1,
    ) -> None:
        if max_repair_attempts < 0:
            raise ValueError("max_repair_attempts must not be negative")
        self._object_store = object_store
        self._scenarios = dict(scenarios)
        self._artifact_bucket = artifact_bucket
        self._max_repair_attempts = max_repair_attempts

    async def generate(self, request: LLMRequest) -> LLMResponse:
        scenario = self._scenario(request.model)
        attempts: list[dict[str, object]] = []
        parsed = None
        text = scenario.responses[0]
        retry_attempts = 0
        for attempt, candidate in enumerate(scenario.responses[: self._max_repair_attempts + 1]):
            text = candidate
            attempts.append({"attempt": attempt, "response": candidate})
            if request.response_schema is None:
                break
            try:
                parsed = parse_structured(candidate, request.response_schema)
                retry_attempts = attempt
                break
            except PermanentPortError:
                if attempt >= self._max_repair_attempts or attempt + 1 >= len(scenario.responses):
                    raise PermanentPortError(
                        "mock output did not satisfy the response schema after bounded repair",
                        port="llm_provider",
                    ) from None

        envelope = {
            "schema_version": 1,
            "provider": "mock",
            "request": _request_payload(request),
            "attempts": attempts,
        }
        raw_ref = await self._store(envelope, correlation_id=request.trace.correlation_id)
        return LLMResponse(
            text=text,
            parsed=parsed,
            finish_reason=scenario.finish_reason,
            usage=TokenUsage(
                input_tokens=scenario.input_tokens,
                output_tokens=scenario.output_tokens,
                cost_usd=scenario.cost_usd,
            ),
            model=request.model,
            provider="mock",
            latency_ms=0,
            raw_artifact_ref=raw_ref,
            retry_attempts=retry_attempts,
        )

    async def embed(
        self, inputs: Sequence[str], *, model: str, secret_ref: SecretRef
    ) -> EmbeddingResponse:
        del secret_ref
        if not inputs:
            raise PermanentPortError("embedding inputs must not be empty", port="llm_provider")
        scenario = self._scenario(model)
        embeddings = scenario.embeddings or tuple(
            _deterministic_embedding(value) for value in inputs
        )
        if len(embeddings) != len(inputs):
            raise PermanentPortError(
                "mock embedding fixture count does not match input count", port="llm_provider"
            )
        envelope = {
            "schema_version": 1,
            "provider": "mock",
            "request": {"model": model, "inputs": list(inputs)},
            "response": {"embeddings": embeddings},
        }
        raw_ref = await self._store(envelope, correlation_id="embedding")
        return EmbeddingResponse(
            embeddings=embeddings,
            model=model,
            usage=TokenUsage(embedding_tokens=sum(len(value.split()) for value in inputs)),
            raw_artifact_ref=raw_ref,
        )

    async def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            structured_output=True,
            deterministic=True,
            max_context_tokens=1_000_000,
            embedding_models=tuple(sorted(self._scenarios)),
        )

    async def health(self) -> HealthStatus:
        return HealthStatus.OK

    async def close(self) -> None:
        """The object store is owned by the composition root, not by this adapter."""

    def _scenario(self, model: str) -> MockScenario:
        try:
            return self._scenarios[model]
        except KeyError as exc:
            raise PermanentPortError(
                f"no mock scenario is registered for model {model!r}", port="llm_provider"
            ) from exc

    async def _store(self, envelope: Mapping[str, object], *, correlation_id: str) -> ObjectRef:
        body = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(body).hexdigest()
        return await self._object_store.put(
            self._artifact_bucket,
            f"llm/{correlation_id}/{digest}.json",
            body,
            content_type="application/json",
            metadata={"provider": "mock", "correlation_id": correlation_id},
        )


def _request_payload(request: LLMRequest) -> dict[str, object]:
    return {
        "model": request.model,
        "messages": [
            {"role": message.role.value, "content": message.content} for message in request.messages
        ],
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
        "stop": list(request.stop),
        "seed": request.seed,
        "response_schema": (
            request.response_schema.model_json_schema() if request.response_schema else None
        ),
    }


def _deterministic_embedding(value: str) -> tuple[float, ...]:
    digest = hashlib.sha256(value.encode()).digest()
    return tuple((byte - 127.5) / 127.5 for byte in digest[:8])


_MOCK_PORT: type[LLMProvider] = MockLLMProvider
