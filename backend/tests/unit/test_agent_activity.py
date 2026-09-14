"""Typed T4-03 logical-agent activity and transaction-ownership tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from temporalio.exceptions import ApplicationError

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.temporal.agent_activity import AgentActivities
from app.application.agent_activity import AgentTurnRunner
from app.db import agent_registry as registry_module
from app.db.agent_registry import SqlAlchemyAgentRegistryFacade
from app.db.session import Database
from app.domain.agent_activity import (
    AgentActivityRunner,
    AgentTurnInput,
    AgentTurnPhase,
    AgentTurnResult,
    ArtifactProposal,
    ProposalBundle,
)
from app.domain.agent_registry import (
    AgentDefinition,
    AgentRegistry,
    AgentRoleKind,
    AgentStatus,
    CredentialEnvelope,
    LLMCallRecord,
    LLMConfiguration,
    ProviderKind,
)
from app.domain.reasoning import ArtifactKind
from app.ports.agent_runtime import PinnedAgentDefinition
from app.ports.errors import PermanentPortError, TransientPortError
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
from app.ports.storage import ObjectRef, SecretRef
from tests.traceability import req

U = tuple(UUID(f"018f0000-0000-7000-8000-{i:012d}") for i in range(1, 10))
PROMPT = b"SEALED SYSTEM PROMPT: propose artifacts only; never commit or advance state."
PROMPT_KEY = "prompts/fiscal-analyst/v3.txt"
TRACE_DIGEST = "sha256:" + "a" * 64


class RecordingRegistry:
    def __init__(self, definition: AgentDefinition, configuration: LLMConfiguration) -> None:
        self.definition = definition
        self.configuration = configuration
        self.records: list[LLMCallRecord] = []

    async def add_configuration(self, configuration: LLMConfiguration) -> None:
        self.configuration = configuration

    async def get_configuration(self, configuration_id: UUID) -> LLMConfiguration | None:
        return self.configuration if configuration_id == self.configuration.id else None

    async def put_credential_envelope(
        self, configuration_id: UUID, workspace_id: UUID, envelope: CredentialEnvelope
    ) -> None:
        del configuration_id, workspace_id, envelope

    async def get_credential_envelope(self, configuration_id: UUID) -> CredentialEnvelope | None:
        del configuration_id
        return None

    async def add_definition(self, definition: AgentDefinition) -> None:
        self.definition = definition

    async def add_definition_version(self, previous_id: UUID, definition: AgentDefinition) -> None:
        del previous_id
        self.definition = definition

    async def get_definition(self, definition_id: UUID) -> AgentDefinition | None:
        return self.definition if definition_id == self.definition.id else None

    async def add_call_record(self, record: LLMCallRecord) -> None:
        self.records.append(record)

    async def list_call_records(self) -> tuple[LLMCallRecord, ...]:
        return tuple(self.records)


class RecordingProvider:
    def __init__(
        self,
        bundle: ProposalBundle | None,
        *,
        error: PermanentPortError | TransientPortError | None = None,
    ) -> None:
        self.bundle = bundle
        self.error = error
        self.requests: list[LLMRequest] = []
        self.close_count = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return LLMResponse(
            text="{}",
            parsed=self.bundle,
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(
                input_tokens=17,
                output_tokens=5,
                cost_usd=Decimal("0.0004"),
            ),
            model=request.model,
            provider="recording",
            latency_ms=12,
            raw_artifact_ref=ObjectRef(
                bucket="artifacts",
                key="llm/trace.json",
                digest=TRACE_DIGEST,
                content_type="application/json",
            ),
        )

    async def embed(
        self, inputs: Sequence[str], *, model: str, secret_ref: SecretRef
    ) -> EmbeddingResponse:
        del inputs, model, secret_ref
        raise NotImplementedError

    async def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(structured_output=True)

    async def health(self) -> HealthStatus:
        return HealthStatus.OK

    async def close(self) -> None:
        self.close_count += 1


def command(
    *,
    round_: int = 1,
    phase: AgentTurnPhase = AgentTurnPhase.ASSESS,
    prompt_hash: str | None = None,
    visible_artifact_json: tuple[str, ...] = (),
    authorized_knowledge_json: str | None = None,
) -> AgentTurnInput:
    digest = prompt_hash or "sha256:" + hashlib.sha256(PROMPT).hexdigest()
    definition = PinnedAgentDefinition(
        id=U[2],
        logical_id=U[7],
        version=3,
        name="fiscal-analyst",
        domain="fiscal",
        role_kind=AgentRoleKind.DOMAIN_EXPERT.value,
        objectives=("Assess fiscal sustainability",),
        constraints=("Never claim coordinator authority",),
        strategy_name="evidence-first",
        strategy_version="1.0.0",
        prompt_ref=PROMPT_KEY,
        prompt_hash=digest,
    )
    return AgentTurnInput(
        protocol_version="1.0",
        kind="turn_request",
        workspace_id=U[0],
        session_id=U[1],
        agent_definition_id=U[2],
        agent_definition_version=3,
        agent_definition_json=definition.model_dump_json(),
        turn_id=U[3],
        correlation_id=U[4],
        causation_id=U[5],
        round=round_,
        phase=phase,
        problem_statement="Choose a fiscally sustainable intervention.",
        canonicalizer_version="canonicalizer@1",
        constraint_summaries=("Debt may not exceed the legal ceiling.",),
        visible_artifact_ids=tuple(U[8] for _value in visible_artifact_json),
        visible_artifact_json=visible_artifact_json,
        authorized_knowledge_json=authorized_knowledge_json,
        sealed=round_ == 1 and phase is AgentTurnPhase.ASSESS,
        budget_remaining_tokens=900,
        timeout_s=12.0,
    )


def bundle(
    *, turn_id: UUID = U[3], limits: tuple[str, ...] = ("No local tax data",)
) -> ProposalBundle:
    return ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=turn_id,
        artifacts=(
            ArtifactProposal(
                op="propose",
                kind=ArtifactKind.CLAIM,
                payload={
                    "statement": "The intervention is affordable under the stated ceiling.",
                    "claim_type": "EVALUATIVE",
                    "direction": "SUPPORTS",
                    "strength": "MODERATE",
                    "supporting_evidence_ids": [],
                    "opposing_evidence_ids": [],
                    "review_status": "PROPOSED",
                },
            ),
        ),
        self_reported_limits=limits,
    )


async def harness(
    response_bundle: ProposalBundle | None,
    *,
    prompt: bytes = PROMPT,
    store_prompt: bool = True,
    prompt_hash: str | None = None,
    provider_error: PermanentPortError | TransientPortError | None = None,
) -> tuple[AgentTurnRunner, RecordingRegistry, RecordingProvider, list[LLMConfiguration]]:
    store = InMemoryObjectStore()
    digest = "sha256:" + hashlib.sha256(prompt).hexdigest()
    if store_prompt:
        await store.put(
            "artifacts",
            PROMPT_KEY,
            prompt,
            content_type="text/plain; charset=utf-8",
            metadata={"kind": "agent-prompt"},
        )
    configuration = LLMConfiguration(
        id=U[6],
        workspace_id=U[0],
        name="test-provider",
        provider_kind=ProviderKind.MOCK,
        base_url="https://provider.invalid/v1",
        model="reasoning-model",
        secret_ref=SecretRef(provider="env_file", name="agent_api_key"),
    )
    definition = AgentDefinition(
        id=U[2],
        workspace_id=U[0],
        logical_id=U[7],
        version=3,
        name="fiscal-analyst",
        domain="fiscal",
        role_kind=AgentRoleKind.DOMAIN_EXPERT,
        objectives=("Assess fiscal sustainability",),
        constraints=("Never claim coordinator authority",),
        strategy_ref="evidence-first",
        strategy_ver="1.0.0",
        prompt_ref=PROMPT_KEY,
        prompt_hash=prompt_hash or digest,
        llm_config_id=configuration.id,
        status=AgentStatus.ACTIVE,
    )
    registry = RecordingRegistry(definition, configuration)
    provider = RecordingProvider(response_bundle, error=provider_error)
    factory_calls: list[LLMConfiguration] = []

    def provider_factory(value: LLMConfiguration) -> LLMProvider:
        factory_calls.append(value)
        return provider

    runner = AgentTurnRunner(
        lambda workspace_id: (
            cast(AgentRegistry, registry)
            if workspace_id == U[0]
            else (_ for _ in ()).throw(AssertionError("wrong workspace"))
        ),
        provider_factory,
        store,
        prompt_bucket="artifacts",
        code_version="test-sha",
    )
    return runner, registry, provider, factory_calls


@req("NFR-016")
async def test_runner_uses_verified_sealed_prompt_records_usage_and_closes_provider() -> None:
    runner, registry, provider, factory_calls = await harness(bundle())

    result = await runner.run(command())

    assert result.turn_id == U[3]
    assert (result.input_tokens, result.output_tokens) == (17, 5)
    assert result.raw_artifact_ref == f"artifacts/llm/trace.json#{TRACE_DIGEST}"
    assert factory_calls == [registry.configuration]
    assert provider.close_count == 1
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.messages[0].content == PROMPT.decode()
    assert request.messages[1].content.startswith(
        f"Return proposal_bundle protocol 1.0 for turn_id {U[3]}."
    )
    assert '"strategy_name": "evidence-first"' in request.messages[1].content
    assert "Authorized retrieval: null." in request.messages[1].content
    assert request.max_output_tokens == 900
    assert request.response_schema is ProposalBundle
    assert len(registry.records) == 1
    assert registry.records[0].id == U[3]
    assert (registry.records[0].input_tokens, registry.records[0].output_tokens) == (17, 5)
    assert registry.records[0].session_id == U[1]
    assert registry.records[0].agent_def_id == U[2]


@req("NFR-016")
async def test_runner_prompt_contains_hydrated_artifact_and_retrieval_provenance() -> None:
    runner, _, provider, _ = await harness(bundle())
    artifact_json = json.dumps(
        {
            "id": str(U[8]),
            "kind": "CLAIM",
            "content_hash": "sha256:" + "b" * 64,
            "payload": {"statement": "Prior finding"},
        },
        sort_keys=True,
    )
    retrieval_json = json.dumps(
        {
            "query_hash": "sha256:" + "c" * 64,
            "requested_namespace_ids": [str(U[6])],
            "searched_namespace_ids": [str(U[6])],
            "index_version": "index@1",
            "embedding_model": "embed-small",
            "embedding_version": "1",
            "reranker_version": "rrf@1",
            "lexical_count": 0,
            "vector_count": 0,
            "degradation": "NONE",
            "warnings": [],
            "chunks": [
                {
                    "namespace_id": str(U[6]),
                    "chunk_id": str(U[7]),
                    "citation": "Policy report, p. 4",
                    "source_content_hash": "sha256:" + "d" * 64,
                    "content_hash": "sha256:" + "e" * 64,
                }
            ],
        },
        sort_keys=True,
    )

    await runner.run(
        command(
            round_=2,
            phase=AgentTurnPhase.ARGUE,
            visible_artifact_json=(artifact_json,),
            authorized_knowledge_json=retrieval_json,
        )
    )

    prompt = provider.requests[0].messages[1].content
    assert '"statement": "Prior finding"' in prompt
    assert '"query_hash": "sha256:' + "c" * 64 + '"' in prompt
    assert '"citation": "Policy report, p. 4"' in prompt
    assert '"source_content_hash": "sha256:' + "d" * 64 + '"' in prompt
    assert '"searched_namespace_ids": ["' + str(U[6]) + '"]' in prompt


@req("NFR-016")
@pytest.mark.parametrize("status", [AgentStatus.DRAFT, AgentStatus.WITHDRAWN])
async def test_runner_rejects_non_runnable_definition_before_provider_creation(
    status: AgentStatus,
) -> None:
    runner, registry, provider, factory_calls = await harness(bundle())
    registry.definition = replace(registry.definition, status=status)

    with pytest.raises(PermanentPortError, match="not runnable"):
        await runner.run(command())

    assert factory_calls == []
    assert provider.requests == []


@req("NFR-016")
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"store_prompt": False}, "not stored"),
        ({"prompt_hash": "sha256:" + "0" * 64}, "digest mismatch"),
        ({"prompt": b"\xff\xfe"}, "not valid UTF-8"),
        ({"prompt": b"  \n"}, "prompt is blank"),
    ],
)
async def test_prompt_dependency_failures_happen_before_provider_creation(
    kwargs: dict[str, Any], message: str
) -> None:
    runner, registry, provider, factory_calls = await harness(bundle(), **kwargs)

    with pytest.raises(PermanentPortError, match=message):
        await runner.run(command(prompt_hash=registry.definition.prompt_hash))

    assert factory_calls == []
    assert provider.requests == []
    assert provider.close_count == 0
    assert registry.records == []


@req("NFR-016")
async def test_provider_failure_closes_provider_without_recording_usage() -> None:
    failure = TransientPortError("provider unavailable", port="llm_provider")
    runner, registry, provider, _ = await harness(bundle(), provider_error=failure)

    with pytest.raises(TransientPortError, match="provider unavailable"):
        await runner.run(command())

    assert provider.close_count == 1
    assert registry.records == []


@req("NFR-016")
async def test_usage_persistence_failure_still_closes_provider() -> None:
    runner, registry, provider, _ = await harness(bundle())

    async def fail_record(_record: LLMCallRecord) -> None:
        raise TransientPortError("database unavailable", port="agent_registry")

    registry.add_call_record = fail_record  # type: ignore[assignment]

    with pytest.raises(TransientPortError, match="database unavailable"):
        await runner.run(command())

    assert len(provider.requests) == 1
    assert provider.close_count == 1
    assert registry.records == []


@req("NFR-016")
@pytest.mark.parametrize(
    ("response_bundle", "message"),
    [
        (bundle(turn_id=U[8]), "another turn"),
        (bundle(limits=()), "at least one limitation"),
        (None, "no typed proposal bundle"),
    ],
)
async def test_completed_but_invalid_provider_result_is_accounted_and_rejected(
    response_bundle: ProposalBundle | None, message: str
) -> None:
    runner, registry, provider, _ = await harness(response_bundle)

    with pytest.raises(PermanentPortError, match=message):
        await runner.run(command())

    assert provider.close_count == 1
    assert len(registry.records) == 1


@req("NFR-016")
@pytest.mark.parametrize(
    "change",
    [
        {"protocol_version": "2.0"},
        {"kind": "round_advance"},
        {"artifacts": [{"op": "commit", "kind": "CLAIM", "payload": {}}]},
        {
            "artifacts": [
                {
                    "op": "propose",
                    "kind": "FACT",
                    "payload": {
                        "statement": "Model-declared fact",
                        "verification": "SOURCE_VERIFIED",
                    },
                }
            ]
        },
        {"artifacts": [{"op": "propose", "kind": "CLAIM", "payload": {}}]},
    ],
)
def test_bundle_rejects_protocol_authority_and_payload_violations(change: dict[str, Any]) -> None:
    raw = bundle().model_dump(mode="json")
    raw.update(change)

    with pytest.raises(ValidationError):
        ProposalBundle.model_validate_json(json.dumps(raw))


@req("NFR-016")
@pytest.mark.parametrize(
    "change",
    [
        {"protocol_version": "2.0"},
        {"kind": "agent_chat"},
        {"schema_version": 2},
        {"sealed": False},
        {"visible_artifact_ids": [str(U[8])]},
    ],
)
def test_turn_request_rejects_version_and_sealed_assessment_violations(
    change: dict[str, Any],
) -> None:
    raw = command().model_dump(mode="json")
    raw.update(change)

    with pytest.raises(ValidationError):
        AgentTurnInput.model_validate_json(json.dumps(raw))


@req("NFR-016")
async def test_temporal_adapter_rejects_malformed_payload_before_delegation() -> None:
    class Runner:
        called = False

        async def run(self, command: AgentTurnInput) -> AgentTurnResult:
            del command
            self.called = True
            raise AssertionError("must not be called")

    runner = Runner()

    with pytest.raises(ApplicationError) as captured:
        await AgentActivities(cast(AgentActivityRunner, runner)).run_turn({"kind": "turn_request"})

    assert captured.value.non_retryable is True
    assert runner.called is False


@req("NFR-016")
async def test_registry_facade_opens_and_closes_a_transaction_per_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions: list[object] = []
    exits: list[object] = []

    class FakeDatabase:
        @asynccontextmanager
        async def session(self, workspace_id: UUID) -> Any:
            assert workspace_id == U[0]
            session = object()
            sessions.append(session)
            try:
                yield session
            finally:
                exits.append(session)

    class FakeScopedRegistry:
        def __init__(self, session: object) -> None:
            self.session = session

        async def get_definition(self, definition_id: UUID) -> AgentDefinition | None:
            assert definition_id == U[2]
            return None

    monkeypatch.setattr(registry_module, "SqlAlchemyAgentRegistry", FakeScopedRegistry)
    facade = SqlAlchemyAgentRegistryFacade(cast(Database, FakeDatabase()), U[0])

    assert await facade.get_definition(U[2]) is None
    assert await facade.get_definition(U[2]) is None

    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert exits == sessions
