"""Provider-boundary acceptance tests for Phase 2 LLM adapters."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.llm import (
    MockLLMProvider,
    MockScenario,
    ModelPrice,
    OpenAICompatibleProvider,
)
from app.ports.errors import PermanentPortError, TransientPortError
from app.ports.health import HealthStatus
from app.ports.llm import LLMCallTrace, LLMMessage, LLMRequest, MessageRole
from app.ports.storage import SecretRef
from tests.traceability import req


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str


class _StrictTupleAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    answers: tuple[str, ...]


class _Secrets:
    def __init__(self, value: str) -> None:
        self.value = value
        self.resolved: list[SecretRef] = []

    async def resolve(self, ref: SecretRef) -> str:
        self.resolved.append(ref)
        return self.value

    async def store(self, ref: SecretRef, value: str) -> None:
        del ref
        self.value = value

    def redact(self, text: str) -> str:
        return text.replace(self.value, "[REDACTED]")

    async def health(self) -> HealthStatus:
        return HealthStatus.OK


def _request(*, model: str = "fixture", structured: bool = True) -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(MessageRole.USER, "Give one answer."),),
        model=model,
        trace=LLMCallTrace(correlation_id="corr-1", session_id="session-1"),
        secret_ref=SecretRef(provider="test", name="llm-key"),
        response_schema=_Answer if structured else None,
        max_output_tokens=128,
        seed=7,
    )


@req("NFR-016")
async def test_mock_repairs_once_and_stores_a_content_addressed_trace() -> None:
    store = InMemoryObjectStore()
    provider = MockLLMProvider(
        store,
        {
            "fixture": MockScenario(
                responses=("not-json", '{"answer":"fixed"}'),
                input_tokens=11,
                output_tokens=4,
                cost_usd=Decimal("0.0003"),
            )
        },
    )

    response = await provider.generate(_request())

    assert response.text == '{"answer":"fixed"}'
    assert response.parsed == _Answer(answer="fixed")
    assert response.retry_attempts == 1
    assert response.usage.total_tokens == 15
    assert response.usage.cost_usd == Decimal("0.0003")
    assert response.raw_artifact_ref.digest.startswith("sha256:")
    trace = json.loads(await store.get(response.raw_artifact_ref))
    assert [item["attempt"] for item in trace["attempts"]] == [0, 1]
    assert trace["request"]["seed"] == 7
    assert "llm-key" not in json.dumps(trace)


@req("NFR-016")
async def test_mock_accepts_json_arrays_for_strict_tuple_fields() -> None:
    provider = MockLLMProvider(
        InMemoryObjectStore(),
        {"fixture": MockScenario(responses=('{"answers":["one","two"]}',))},
    )
    request = replace(_request(), response_schema=_StrictTupleAnswer)

    response = await provider.generate(request)

    assert response.parsed == _StrictTupleAnswer(answers=("one", "two"))


@req("NFR-016")
async def test_mock_structured_repair_is_bounded() -> None:
    provider = MockLLMProvider(
        InMemoryObjectStore(),
        {"fixture": MockScenario(responses=("bad", "still-bad", '{"answer":"late"}'))},
        max_repair_attempts=1,
    )

    with pytest.raises(PermanentPortError, match="after bounded repair"):
        await provider.generate(_request())


@req("NFR-016")
async def test_mock_embeddings_are_deterministic_and_reject_empty_input() -> None:
    provider = MockLLMProvider(
        InMemoryObjectStore(), {"fixture": MockScenario(responses=("unused",))}
    )
    secret_ref = SecretRef(provider="test", name="unused")

    first = await provider.embed(("alpha", "beta"), model="fixture", secret_ref=secret_ref)
    second = await provider.embed(("alpha", "beta"), model="fixture", secret_ref=secret_ref)

    assert first.embeddings == second.embeddings
    assert len(first.embeddings) == 2
    assert first.usage.embedding_tokens == 2
    with pytest.raises(PermanentPortError, match="must not be empty"):
        await provider.embed((), model="fixture", secret_ref=secret_ref)


@req("NFR-016")
async def test_openai_adapter_repairs_and_accounts_for_every_billable_attempt() -> None:
    sent: list[dict[str, object]] = []
    responses = iter(
        (
            {
                "choices": [{"message": {"content": "not-json"}, "finish_reason": "stop"}],
                "model": "remote-model",
                "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            },
            {
                "choices": [
                    {"message": {"content": '{"answer":"valid"}'}, "finish_reason": "stop"}
                ],
                "model": "remote-model",
                "usage": {"prompt_tokens": 120, "completion_tokens": 5},
            },
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer top-secret"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=next(responses))

    store = InMemoryObjectStore()
    secrets = _Secrets("top-secret")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ticks = iter((10.0, 10.25))
    provider = OpenAICompatibleProvider(
        "https://provider.example/v1",
        secrets,
        store,
        client=client,
        prices={
            "fixture": ModelPrice(input_per_million=Decimal("2"), output_per_million=Decimal("6"))
        },
        monotonic=lambda: next(ticks),
    )

    response = await provider.generate(_request())
    await client.aclose()

    assert response.parsed == _Answer(answer="valid")
    assert response.retry_attempts == 1
    assert response.latency_ms == 250
    assert response.usage.input_tokens == 220
    assert response.usage.output_tokens == 15
    assert response.usage.cost_usd == Decimal("0.00053")
    assert len(sent) == 2
    assert len(sent[1]["messages"]) == 3  # type: ignore[arg-type]
    assert "JSON Schema" in sent[1]["messages"][2]["content"]  # type: ignore[index]
    trace_bytes = await store.get(response.raw_artifact_ref)
    assert b"top-secret" not in trace_bytes
    assert len(json.loads(trace_bytes)["attempts"]) == 2
    assert secrets.resolved == [_request().secret_ref]


@req("NFR-016")
async def test_openai_embeddings_restore_provider_indices_and_use_decimal_costs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [3, 4.5]},
                    {"index": 0, "embedding": [1.0, 2]},
                ],
                "usage": {"prompt_tokens": 250},
            },
        )

    store = InMemoryObjectStore()
    secrets = _Secrets("secret")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        "https://provider.example/v1",
        secrets,
        store,
        client=client,
        prices={"embedding": ModelPrice(embedding_per_million=Decimal("0.02"))},
    )

    response = await provider.embed(
        ("first", "second"),
        model="embedding",
        secret_ref=SecretRef(provider="test", name="embedding-key"),
    )
    await client.aclose()

    assert response.embeddings == ((1.0, 2.0), (3.0, 4.5))
    assert response.usage.embedding_tokens == 250
    assert response.usage.cost_usd == Decimal("0.000005")


@req("NFR-016")
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, PermanentPortError),
        (401, PermanentPortError),
        (429, TransientPortError),
        (503, TransientPortError),
    ],
)
async def test_openai_http_failures_are_normalized(
    status: int, expected: type[PermanentPortError | TransientPortError]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "provider detail"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        "https://provider.example/v1",
        _Secrets("secret"),
        InMemoryObjectStore(),
        client=client,
    )

    with pytest.raises(expected, match=f"HTTP {status}"):
        await provider.generate(_request(structured=False))
    await client.aclose()
