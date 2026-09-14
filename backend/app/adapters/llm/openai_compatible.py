"""OpenAI-compatible HTTP adapter without a provider SDK (ADR-006)."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

import httpx

from app.adapters.llm.structured import parse_structured, repair_instruction
from app.observability.logging import redact_text
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.health import HealthStatus
from app.ports.llm import (
    EmbeddingResponse,
    FinishReason,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    MessageRole,
    ProviderCapabilities,
    TokenUsage,
)
from app.ports.storage import ObjectRef, ObjectStore, SecretProvider, SecretRef

__all__ = ["ModelPrice", "OpenAICompatibleProvider"]


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD per one million tokens at the time a configuration is created."""

    input_per_million: Decimal = Decimal("0")
    output_per_million: Decimal = Decimal("0")
    embedding_per_million: Decimal = Decimal("0")


class OpenAICompatibleProvider:
    """Translate the platform contract to chat-completions and embeddings HTTP calls."""

    def __init__(
        self,
        base_url: str,
        secret_provider: SecretProvider,
        object_store: ObjectStore,
        *,
        client: httpx.AsyncClient | None = None,
        prices: Mapping[str, ModelPrice] | None = None,
        capabilities: ProviderCapabilities | None = None,
        artifact_bucket: str = "llm-traces",
        max_repair_attempts: int = 1,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if max_repair_attempts < 0:
            raise ValueError("max_repair_attempts must not be negative")
        self._base_url = base_url.rstrip("/")
        self._secret_provider = secret_provider
        self._object_store = object_store
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._prices = dict(prices or {})
        self._capabilities = capabilities or ProviderCapabilities(structured_output=True)
        self._artifact_bucket = artifact_bucket
        self._max_repair_attempts = max_repair_attempts
        self._monotonic = monotonic

    async def generate(self, request: LLMRequest) -> LLMResponse:
        api_key = await self._secret_provider.resolve(request.secret_ref)
        messages = list(request.messages)
        attempts: list[dict[str, object]] = []
        started = self._monotonic()
        parsed = None
        text = ""
        response_payload: Mapping[str, object] = {}
        retry_attempts = 0
        price = self._prices.get(request.model, ModelPrice())
        usage = TokenUsage()
        for attempt in range(self._max_repair_attempts + 1):
            request_payload = _generation_payload(request, messages)
            response_payload = await self._post(
                "/chat/completions", request_payload, api_key=api_key, timeout_s=request.timeout_s
            )
            usage = _add_usage(usage, _usage(response_payload, price))
            attempts.append({"request": request_payload, "response": response_payload})
            text = _completion_text(response_payload)
            if request.response_schema is None:
                break
            try:
                parsed = parse_structured(text, request.response_schema)
                retry_attempts = attempt
                break
            except PermanentPortError:
                if attempt >= self._max_repair_attempts:
                    raise PermanentPortError(
                        "provider output did not satisfy the response schema after bounded repair",
                        port="llm_provider",
                    ) from None
                messages.extend(
                    (
                        LLMMessage(MessageRole.ASSISTANT, text or "null"),
                        LLMMessage(MessageRole.USER, repair_instruction(request.response_schema)),
                    )
                )

        elapsed_ms = max(0, round((self._monotonic() - started) * 1000))
        envelope = {
            "schema_version": 1,
            "provider": "openai_compatible",
            "base_url": self._base_url,
            "attempts": attempts,
        }
        raw_ref = await self._store(envelope, correlation_id=request.trace.correlation_id)
        return LLMResponse(
            text=text,
            parsed=parsed,
            finish_reason=_finish_reason(response_payload),
            usage=usage,
            model=str(response_payload.get("model") or request.model),
            provider="openai_compatible",
            latency_ms=elapsed_ms,
            raw_artifact_ref=raw_ref,
            retry_attempts=retry_attempts,
        )

    async def embed(
        self, inputs: Sequence[str], *, model: str, secret_ref: SecretRef
    ) -> EmbeddingResponse:
        if not inputs:
            raise PermanentPortError("embedding inputs must not be empty", port="llm_provider")
        api_key = await self._secret_provider.resolve(secret_ref)
        request_payload: dict[str, object] = {"input": list(inputs), "model": model}
        response_payload = await self._post(
            "/embeddings", request_payload, api_key=api_key, timeout_s=30.0
        )
        embeddings = _embeddings(response_payload, expected=len(inputs))
        price = self._prices.get(model, ModelPrice())
        usage = _embedding_usage(response_payload, price)
        raw_ref = await self._store(
            {
                "schema_version": 1,
                "provider": "openai_compatible",
                "base_url": self._base_url,
                "request": request_payload,
                "response": response_payload,
            },
            correlation_id="embedding",
        )
        return EmbeddingResponse(
            embeddings=embeddings,
            model=str(response_payload.get("model") or model),
            usage=usage,
            raw_artifact_ref=raw_ref,
        )

    async def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def health(self) -> HealthStatus:
        try:
            response = await self._client.get(f"{self._base_url}/models", timeout=2.0)
        except httpx.HTTPError:
            return HealthStatus.DOWN
        return HealthStatus.OK if response.is_success else HealthStatus.DOWN

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _post(
        self,
        path: str,
        payload: Mapping[str, object],
        *,
        api_key: str,
        timeout_s: float,
    ) -> Mapping[str, object]:
        try:
            response = await self._client.post(
                f"{self._base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout_s,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TransientPortError(
                "LLM provider request failed transiently", port="llm_provider", cause=exc
            ) from exc
        except httpx.HTTPError as exc:
            raise PermanentPortError(
                "LLM provider request failed", port="llm_provider", cause=exc
            ) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientPortError(
                f"LLM provider returned HTTP {response.status_code}", port="llm_provider"
            )
        if not response.is_success:
            raise PermanentPortError(
                f"LLM provider returned HTTP {response.status_code}", port="llm_provider"
            )
        try:
            decoded = response.json()
        except ValueError as exc:
            raise PermanentPortError(
                "LLM provider returned invalid JSON", port="llm_provider", cause=exc
            ) from exc
        if not isinstance(decoded, dict):
            raise PermanentPortError(
                "LLM provider returned a non-object JSON body", port="llm_provider"
            )
        return cast(dict[str, object], decoded)

    async def _store(self, envelope: Mapping[str, object], *, correlation_id: str) -> ObjectRef:
        rendered = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        redacted = self._secret_provider.redact(redact_text(rendered)).encode()
        digest = hashlib.sha256(redacted).hexdigest()
        return await self._object_store.put(
            self._artifact_bucket,
            f"llm/{correlation_id}/{digest}.json",
            redacted,
            content_type="application/json",
            metadata={"provider": "openai_compatible", "correlation_id": correlation_id},
        )


def _generation_payload(request: LLMRequest, messages: Sequence[LLMMessage]) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": request.model,
        "messages": [
            {"role": message.role.value, "content": message.content} for message in messages
        ],
        "temperature": request.temperature,
        "max_tokens": request.max_output_tokens,
    }
    if request.stop:
        payload["stop"] = list(request.stop)
    if request.seed is not None:
        payload["seed"] = request.seed
    if request.response_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.response_schema.__name__,
                "strict": True,
                "schema": request.response_schema.model_json_schema(),
            },
        }
    return payload


def _completion_text(payload: Mapping[str, object]) -> str:
    try:
        choices = cast(list[object], payload["choices"])
        choice = cast(dict[str, object], choices[0])
        message = cast(dict[str, object], choice["message"])
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PermanentPortError(
            "LLM provider response omitted completion content", port="llm_provider", cause=exc
        ) from exc
    if not isinstance(content, str):
        raise PermanentPortError("LLM completion content is not text", port="llm_provider")
    return content


def _finish_reason(payload: Mapping[str, object]) -> FinishReason:
    try:
        choice = cast(dict[str, object], cast(list[object], payload["choices"])[0])
        raw = str(choice.get("finish_reason") or "unknown")
    except (KeyError, IndexError, TypeError):
        raw = "unknown"
    aliases = {"tool_calls": FinishReason.TOOL_CALL}
    if raw in FinishReason:
        return FinishReason(raw)
    return aliases.get(raw, FinishReason.UNKNOWN)


def _usage(payload: Mapping[str, object], price: ModelPrice) -> TokenUsage:
    usage = payload.get("usage")
    values = cast(Mapping[str, object], usage) if isinstance(usage, dict) else {}
    input_tokens = _integer(values.get("prompt_tokens"))
    output_tokens = _integer(values.get("completion_tokens"))
    cost = (
        Decimal(input_tokens) * price.input_per_million
        + Decimal(output_tokens) * price.output_per_million
    ) / Decimal(1_000_000)
    return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost)


def _embedding_usage(payload: Mapping[str, object], price: ModelPrice) -> TokenUsage:
    usage = payload.get("usage")
    values = cast(Mapping[str, object], usage) if isinstance(usage, dict) else {}
    tokens = _integer(values.get("prompt_tokens") or values.get("total_tokens"))
    return TokenUsage(
        embedding_tokens=tokens,
        cost_usd=Decimal(tokens) * price.embedding_per_million / Decimal(1_000_000),
    )


def _add_usage(left: TokenUsage, right: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        embedding_tokens=left.embedding_tokens + right.embedding_tokens,
        cost_usd=left.cost_usd + right.cost_usd,
    )


def _embeddings(payload: Mapping[str, object], *, expected: int) -> tuple[tuple[float, ...], ...]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise PermanentPortError("LLM embedding response omitted data", port="llm_provider")
    ordered: list[tuple[int, tuple[float, ...]]] = []
    try:
        for fallback_index, item in enumerate(data):
            row = cast(dict[str, object], item)
            vector = cast(list[object], row["embedding"])
            raw_index = row.get("index")
            index = fallback_index if raw_index is None else _required_integer(raw_index)
            ordered.append(
                (
                    index,
                    tuple(_numeric(value) for value in vector),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise PermanentPortError(
            "LLM embedding response contained invalid vectors", port="llm_provider", cause=exc
        ) from exc
    ordered.sort(key=lambda pair: pair[0])
    if [index for index, _ in ordered] != list(range(expected)):
        raise PermanentPortError(
            "LLM embedding response indices do not match input order", port="llm_provider"
        )
    result = tuple(vector for _, vector in ordered)
    if len(result) != expected:
        raise PermanentPortError(
            "LLM embedding response count does not match input count", port="llm_provider"
        )
    return result


def _integer(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return default


def _required_integer(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("embedding indices must be integers")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise TypeError("embedding indices must be integers")


def _numeric(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("embedding values must be JSON numbers")
    return float(value)


_OPENAI_PORT: type[LLMProvider] = OpenAICompatibleProvider
