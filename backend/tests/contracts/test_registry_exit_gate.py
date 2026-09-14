"""Phase 2 exit gate: one agent, two remote providers, one deterministic mock."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import cast
from uuid import uuid4

import httpx

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.llm import (
    MockLLMProvider,
    MockScenario,
    ModelPrice,
    OpenAICompatibleProvider,
)
from app.application.llm import LLMCallRunner
from app.domain.agent_registry import (
    AgentDefinition,
    AgentRegistry,
    AgentRoleKind,
    LLMCallRecord,
)
from app.ports.health import HealthStatus
from app.ports.llm import LLMCallTrace, LLMMessage, LLMRequest, MessageRole
from app.ports.storage import SecretRef
from tests.traceability import req


class _CallRegistry:
    """Record the only registry operation exercised by ``LLMCallRunner``."""

    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    async def add_call_record(self, record: LLMCallRecord) -> None:
        self.records.append(record)


class _StaticSecrets:
    def __init__(self, value: str) -> None:
        self.value = value

    async def resolve(self, ref: SecretRef) -> str:
        del ref
        return self.value

    async def store(self, ref: SecretRef, value: str) -> None:
        del ref
        self.value = value

    def redact(self, text: str) -> str:
        return text.replace(self.value, "[REDACTED]")

    async def health(self) -> HealthStatus:
        return HealthStatus.OK


def _request(*, model: str, correlation_id: str) -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(MessageRole.USER, "Evaluate the shared proposal."),),
        model=model,
        trace=LLMCallTrace(correlation_id=correlation_id),
        secret_ref=SecretRef(provider="test", name="phase-2-key"),
    )


def _completion_handler(
    *, host: str, model: str, answer: str, input_tokens: int, output_tokens: int
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == host
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer phase-2-secret"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
                "model": model,
                "usage": {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                },
            },
        )

    return handler


@req("FR-1005")
async def test_same_agent_runs_against_two_providers_and_mock_with_traceable_records() -> None:
    workspace_id = uuid4()
    agent = AgentDefinition(
        id=uuid4(),
        workspace_id=workspace_id,
        logical_id=uuid4(),
        version=1,
        name="shared-policy-expert",
        domain="policy",
        role_kind=AgentRoleKind.DOMAIN_EXPERT,
        objectives=("Evaluate the proposal consistently across providers.",),
    )
    alpha_config_id, beta_config_id, mock_config_id = uuid4(), uuid4(), uuid4()
    store = InMemoryObjectStore()
    secrets = _StaticSecrets("phase-2-secret")
    registry = _CallRegistry()
    registry_port = cast(AgentRegistry, registry)

    alpha_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            _completion_handler(
                host="alpha.vendor.test",
                model="alpha-model",
                answer="alpha answer",
                input_tokens=11,
                output_tokens=3,
            )
        )
    )
    beta_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            _completion_handler(
                host="beta.vendor.test",
                model="beta-model",
                answer="beta answer",
                input_tokens=13,
                output_tokens=5,
            )
        )
    )
    alpha = OpenAICompatibleProvider(
        "https://alpha.vendor.test/v1",
        secrets,
        store,
        client=alpha_client,
        prices={
            "alpha-model": ModelPrice(
                input_per_million=Decimal("1"), output_per_million=Decimal("2")
            )
        },
    )
    beta = OpenAICompatibleProvider(
        "https://beta.vendor.test/v1",
        secrets,
        store,
        client=beta_client,
        prices={
            "beta-model": ModelPrice(
                input_per_million=Decimal("2"), output_per_million=Decimal("4")
            )
        },
    )
    mock = MockLLMProvider(
        store,
        {
            "mock-model": MockScenario(
                responses=("mock answer",),
                input_tokens=7,
                output_tokens=2,
                cost_usd=Decimal("0.000009"),
            )
        },
    )

    try:
        alpha_response = await LLMCallRunner(alpha, registry_port).generate(
            _request(model="alpha-model", correlation_id="phase2-alpha"),
            workspace_id=workspace_id,
            llm_config_id=alpha_config_id,
            agent_def_id=agent.id,
        )
        beta_response = await LLMCallRunner(beta, registry_port).generate(
            _request(model="beta-model", correlation_id="phase2-beta"),
            workspace_id=workspace_id,
            llm_config_id=beta_config_id,
            agent_def_id=agent.id,
        )
        mock_response = await LLMCallRunner(mock, registry_port).generate(
            _request(model="mock-model", correlation_id="phase2-mock"),
            workspace_id=workspace_id,
            llm_config_id=mock_config_id,
            agent_def_id=agent.id,
        )
    finally:
        await alpha_client.aclose()
        await beta_client.aclose()

    assert [alpha_response.text, beta_response.text, mock_response.text] == [
        "alpha answer",
        "beta answer",
        "mock answer",
    ]
    assert [record.agent_def_id for record in registry.records] == [agent.id] * 3
    assert [record.llm_config_id for record in registry.records] == [
        alpha_config_id,
        beta_config_id,
        mock_config_id,
    ]
    assert [record.provider for record in registry.records] == [
        "openai_compatible",
        "openai_compatible",
        "mock",
    ]
    assert [record.correlation_id for record in registry.records] == [
        "phase2-alpha",
        "phase2-beta",
        "phase2-mock",
    ]
    assert [(record.input_tokens, record.output_tokens) for record in registry.records] == [
        (11, 3),
        (13, 5),
        (7, 2),
    ]
    assert all(record.cost_usd > 0 for record in registry.records)
    assert all("#sha256:" in record.raw_artifact_ref for record in registry.records)

    traces = [
        json.loads(await store.get(response.raw_artifact_ref))
        for response in (alpha_response, beta_response, mock_response)
    ]
    assert [trace["provider"] for trace in traces] == [
        "openai_compatible",
        "openai_compatible",
        "mock",
    ]
    assert [trace.get("base_url") for trace in traces] == [
        "https://alpha.vendor.test/v1",
        "https://beta.vendor.test/v1",
        None,
    ]
    assert "phase-2-secret" not in json.dumps(traces)
