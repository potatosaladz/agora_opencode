"""Acceptance tests for mandatory provider-independent LLM call accounting."""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.llm.mock import MockLLMProvider, MockScenario
from app.application.llm import LLMCallRunner
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
from app.ports.errors import PermanentPortError
from app.ports.llm import LLMCallTrace, LLMMessage, LLMRequest, MessageRole
from app.ports.storage import SecretRef
from tests.traceability import req


class _RecordingRegistry:
    """In-memory double that mirrors the SQL registry's observable semantics.

    Versioning mirrors ``SqlAlchemyAgentRegistry.add_definition_version``: it requires an
    existing previous version with the same ``logical_id`` and exactly ``version + 1``.
    """

    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []
        self.configurations: dict[UUID, LLMConfiguration] = {}
        self.envelopes: dict[UUID, CredentialEnvelope] = {}
        self.definitions: dict[UUID, AgentDefinition] = {}

    async def add_configuration(self, configuration: LLMConfiguration) -> None:
        self.configurations[configuration.id] = configuration

    async def get_configuration(self, configuration_id: UUID) -> LLMConfiguration | None:
        return self.configurations.get(configuration_id)

    async def put_credential_envelope(
        self, configuration_id: UUID, workspace_id: UUID, envelope: CredentialEnvelope
    ) -> None:
        assert isinstance(configuration_id, UUID)
        assert isinstance(workspace_id, UUID)
        self.envelopes[configuration_id] = envelope

    async def get_credential_envelope(self, configuration_id: UUID) -> CredentialEnvelope | None:
        return self.envelopes.get(configuration_id)

    async def add_definition(self, definition: AgentDefinition) -> None:
        self.definitions[definition.id] = definition

    async def add_definition_version(self, previous_id: UUID, definition: AgentDefinition) -> None:
        previous = self.definitions.get(previous_id)
        if previous is None:
            raise ValueError("previous agent definition does not exist")
        if (
            definition.logical_id != previous.logical_id
            or definition.version != previous.version + 1
        ):
            raise ValueError("agent definition version must follow the same logical definition")
        self.definitions[definition.id] = definition
        self.definitions[previous_id] = _deprecate(previous, superseded_by=definition.id)

    async def get_definition(self, definition_id: UUID) -> AgentDefinition | None:
        return self.definitions.get(definition_id)

    async def add_call_record(self, record: LLMCallRecord) -> None:
        self.records.append(record)

    async def list_call_records(self) -> tuple[LLMCallRecord, ...]:
        return tuple(self.records)


def _deprecate(definition: AgentDefinition, *, superseded_by: UUID) -> AgentDefinition:
    """Return a copy of ``definition`` marked DEPRECATED, without mutating the frozen original."""
    return AgentDefinition(
        id=definition.id,
        workspace_id=definition.workspace_id,
        logical_id=definition.logical_id,
        version=definition.version,
        name=definition.name,
        domain=definition.domain,
        role_kind=definition.role_kind,
        objectives=definition.objectives,
        constraints=definition.constraints,
        knowledge_ns=definition.knowledge_ns,
        strategy_ref=definition.strategy_ref,
        strategy_ver=definition.strategy_ver,
        prompt_ref=definition.prompt_ref,
        prompt_hash=definition.prompt_hash,
        llm_config_id=definition.llm_config_id,
        tool_perms=definition.tool_perms,
        budget=definition.budget,
        status=AgentStatus.DEPRECATED,
        superseded_by=superseded_by,
        referenced_at=definition.referenced_at,
        created_at=definition.created_at,
        updated_at=definition.updated_at,
    )


def _request(model: str = "fixture") -> LLMRequest:
    return LLMRequest(
        model=model,
        messages=(LLMMessage(role=MessageRole.USER, content="question"),),
        secret_ref=SecretRef(provider="test", name="unused"),
        trace=LLMCallTrace(correlation_id="corr-42", agent_id="agent-7"),
    )


@req("FR-202", "FR-210", "FR-1005")
async def test_runner_persists_normalized_cost_usage_and_trace() -> None:
    registry = _RecordingRegistry()
    provider = MockLLMProvider(
        InMemoryObjectStore(),
        {
            "fixture": MockScenario(
                responses=("answer",),
                input_tokens=17,
                output_tokens=5,
                cost_usd=Decimal("0.012345"),
            )
        },
    )
    workspace_id, config_id, agent_id = uuid4(), uuid4(), uuid4()

    response = await LLMCallRunner(provider, cast(AgentRegistry, registry)).generate(
        _request(), workspace_id=workspace_id, llm_config_id=config_id, agent_def_id=agent_id
    )

    assert response.text == "answer"
    assert len(registry.records) == 1
    record = registry.records[0]
    assert (record.input_tokens, record.output_tokens) == (17, 5)
    assert record.cost_usd == Decimal("0.012345")
    assert record.correlation_id == "corr-42"
    assert record.workspace_id == workspace_id
    assert record.llm_config_id == config_id
    assert record.agent_def_id == agent_id
    assert record.raw_artifact_ref.startswith("llm-traces/llm/corr-42/")
    assert "#sha256:" in record.raw_artifact_ref


@req("FR-202", "FR-210", "FR-1005")
async def test_runner_does_not_record_a_call_without_provider_response() -> None:
    registry = _RecordingRegistry()
    provider = MockLLMProvider(InMemoryObjectStore(), {"fixture": MockScenario(("answer",))})

    with pytest.raises(PermanentPortError, match="no mock scenario"):
        await LLMCallRunner(provider, cast(AgentRegistry, registry)).generate(
            _request("absent"), workspace_id=uuid4()
        )

    assert registry.records == []


def _configuration(workspace_id: UUID, *, name: str = "fixture-endpoint") -> LLMConfiguration:
    return LLMConfiguration(
        id=uuid4(),
        workspace_id=workspace_id,
        name=name,
        provider_kind=ProviderKind.MOCK,
        base_url="https://example.invalid/v1",
        model="fixture",
        secret_ref=SecretRef(provider="env_file", name="llm_master_key"),
    )


def _envelope(*, master_key_version: int | None = None) -> CredentialEnvelope:
    return CredentialEnvelope(
        ciphertext=b"ciphertext",
        credential_nonce=b"credential-nonce",
        wrapped_data_key=b"wrapped-data-key",
        wrapping_nonce=b"wrapping-nonce",
        master_key_ref=SecretRef(
            provider="env_file", name="llm_master_key", version=master_key_version
        ),
    )


@req("FR-202", "FR-210", "FR-1005")
async def test_registry_credential_envelope_round_trip_is_lossless() -> None:
    registry = _RecordingRegistry()
    configuration = _configuration(workspace_id=uuid4())
    await registry.add_configuration(configuration)
    assert await registry.get_configuration(configuration.id) == configuration

    envelope = _envelope(master_key_version=3)
    await registry.put_credential_envelope(configuration.id, configuration.workspace_id, envelope)

    stored = await registry.get_credential_envelope(configuration.id)
    assert stored is not None
    assert stored == envelope
    assert stored.master_key_ref.version == 3
    assert await registry.get_credential_envelope(uuid4()) is None


@req("FR-202", "FR-210", "FR-1005")
async def test_registry_definition_versioning_deprecates_the_previous_version() -> None:
    registry = _RecordingRegistry()
    workspace_id = uuid4()
    logical_id = uuid4()
    first = AgentDefinition(
        id=uuid4(),
        workspace_id=workspace_id,
        logical_id=logical_id,
        version=1,
        name="price-expert",
        domain="pricing",
        role_kind=AgentRoleKind.DOMAIN_EXPERT,
        status=AgentStatus.ACTIVE,
    )
    second = AgentDefinition(
        id=uuid4(),
        workspace_id=workspace_id,
        logical_id=logical_id,
        version=2,
        name="price-expert",
        domain="pricing",
        role_kind=AgentRoleKind.DOMAIN_EXPERT,
        status=AgentStatus.ACTIVE,
    )

    await registry.add_definition(first)
    await registry.add_definition_version(first.id, second)

    previous = await registry.get_definition(first.id)
    assert previous is not None
    assert previous.status is AgentStatus.DEPRECATED
    assert previous.superseded_by == second.id
    assert await registry.get_definition(second.id) == second


@req("FR-202", "FR-210", "FR-1005")
@pytest.mark.parametrize("kind", ["missing-previous", "logical-mismatch", "skipped-version"])
async def test_registry_definition_versioning_rejects_invalid_successors(kind: str) -> None:
    registry = _RecordingRegistry()
    workspace_id = uuid4()
    first = AgentDefinition(
        id=uuid4(),
        workspace_id=workspace_id,
        logical_id=uuid4(),
        version=1,
        name="price-expert",
        domain="pricing",
        role_kind=AgentRoleKind.DOMAIN_EXPERT,
    )
    await registry.add_definition(first)

    if kind == "missing-previous":
        successor = AgentDefinition(
            id=uuid4(),
            workspace_id=workspace_id,
            logical_id=first.logical_id,
            version=2,
            name="price-expert",
            domain="pricing",
            role_kind=AgentRoleKind.DOMAIN_EXPERT,
        )
        with pytest.raises(ValueError, match="previous agent definition does not exist"):
            await registry.add_definition_version(uuid4(), successor)
    else:
        successor = AgentDefinition(
            id=uuid4(),
            workspace_id=workspace_id,
            logical_id=first.logical_id if kind == "skipped-version" else uuid4(),
            version=first.version if kind == "logical-mismatch" else first.version + 2,
            name="price-expert",
            domain="pricing",
            role_kind=AgentRoleKind.DOMAIN_EXPERT,
        )
        with pytest.raises(ValueError, match="must follow the same logical definition"):
            await registry.add_definition_version(first.id, successor)

    assert first.status is AgentStatus.DRAFT
    assert (await registry.get_definition(first.id)) == first


@req("FR-202", "FR-210", "FR-1005")
async def test_registry_call_records_keep_insertion_order() -> None:
    registry = _RecordingRegistry()
    provider = MockLLMProvider(
        InMemoryObjectStore(),
        {
            "fixture": MockScenario(
                responses=("one", "two", "three"),
                input_tokens=3,
                output_tokens=1,
                cost_usd=Decimal("0.0001"),
            )
        },
    )
    runner = LLMCallRunner(provider, cast(AgentRegistry, registry))

    for _index in range(3):
        await runner.generate(
            _request(), workspace_id=uuid4(), llm_config_id=uuid4(), agent_def_id=uuid4()
        )

    records = await registry.list_call_records()
    assert [record.correlation_id for record in records] == ["corr-42", "corr-42", "corr-42"]
    assert len(records) == 3
    assert records == tuple(registry.records)
