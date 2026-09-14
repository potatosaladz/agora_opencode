"""FR-205 contract: shipped Critic attacks all artifact kinds through the real activity."""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.llm.mock import MockLLMProvider, MockScenario
from app.application.agent_activity import AgentTurnRunner
from app.application.critic import (
    CRITIC_PROMPT_BUCKET,
    build_critic_definition,
    pinned_critic,
    stage_critic_prompt,
)
from app.domain.agent_activity import (
    AgentTurnInput,
    AgentTurnPhase,
    ArtifactProposal,
    ProposalBundle,
)
from app.domain.agent_registry import (
    AgentDefinition,
    AgentRegistry,
    CredentialEnvelope,
    LLMCallRecord,
    LLMConfiguration,
    ProviderKind,
)
from app.domain.critique import CritiqueAssignment, validate_critic_bundle
from app.domain.reasoning import (
    ArtifactKind,
    CritiquePayload,
    CritiqueType,
    validate_artifact_payload,
)
from app.ports.storage import SecretRef
from tests.traceability import req

WORKSPACE_ID = UUID("018f4000-0000-7000-8000-000000000001")
CONFIGURATION_ID = UUID("018f4000-0000-7000-8000-000000000002")
SESSION_ID = UUID("018f4000-0000-7000-8000-000000000003")
TURN_ID = UUID("018f4000-0000-7000-8000-000000000004")
CORRELATION_ID = UUID("018f4000-0000-7000-8000-000000000005")
CAUSATION_ID = UUID("018f4000-0000-7000-8000-000000000006")
TARGET_IDS = tuple(UUID(f"018f4000-0000-7000-8000-{index:012d}") for index in range(20, 34))


class _CriticRegistry:
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


@req("FR-205")
@pytest.mark.contract
async def test_shipped_critic_attacks_every_artifact_kind_through_real_activity() -> None:
    store = InMemoryObjectStore()
    definition = build_critic_definition(WORKSPACE_ID, CONFIGURATION_ID)
    await stage_critic_prompt(store)
    configuration = LLMConfiguration(
        id=CONFIGURATION_ID,
        workspace_id=WORKSPACE_ID,
        name="T7-02 deterministic mock",
        provider_kind=ProviderKind.MOCK,
        base_url="mock://local",
        model="critic-fixture",
        secret_ref=SecretRef(provider="none", name="none"),
    )
    registry = _CriticRegistry(definition, configuration)
    critique_types = tuple(CritiqueType)
    proposals = tuple(
        ArtifactProposal(
            op="propose",
            kind=ArtifactKind.CRITIQUE,
            payload={
                "target_id": target_id,
                "critique_type": critique_types[index % len(critique_types)],
                "severity": "HIGH",
                "argument": f"Deterministic defect for {artifact_kind.value}.",
                "resolution": "OPEN",
            },
        )
        for index, (artifact_kind, target_id) in enumerate(
            zip(ArtifactKind, TARGET_IDS, strict=True)
        )
    )
    bundle = ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=TURN_ID,
        artifacts=proposals,
        self_reported_limits=("Fixture criticism has no external evidence.",),
    )

    def provider_factory(_configuration: LLMConfiguration) -> MockLLMProvider:
        return MockLLMProvider(
            store,
            {
                "critic-fixture": MockScenario(
                    responses=(bundle.model_dump_json(),),
                    input_tokens=37,
                    output_tokens=53,
                    cost_usd=Decimal("0"),
                )
            },
        )

    runner = AgentTurnRunner(
        lambda workspace_id: (
            cast(AgentRegistry, registry)
            if workspace_id == WORKSPACE_ID
            else pytest.fail("cross-workspace registry lookup")
        ),
        provider_factory,
        store,
        prompt_bucket=CRITIC_PROMPT_BUCKET,
        code_version="t7-02-contract",
    )
    snapshot = pinned_critic(definition)
    result = await runner.run(
        AgentTurnInput(
            protocol_version="1.0",
            kind="turn_request",
            workspace_id=WORKSPACE_ID,
            session_id=SESSION_ID,
            agent_definition_id=definition.id,
            agent_definition_version=definition.version,
            agent_definition_json=snapshot.model_dump_json(),
            turn_id=TURN_ID,
            correlation_id=CORRELATION_ID,
            causation_id=CAUSATION_ID,
            round=2,
            phase=AgentTurnPhase.CRITIQUE,
            problem_statement="Critique a complete typed reasoning fixture.",
            objective_summaries=definition.objectives,
            constraint_summaries=definition.constraints,
            visible_artifact_ids=TARGET_IDS,
            visible_artifact_json=tuple(
                f'{{"id":"{target_id}","kind":"{kind.value}"}}'
                for kind, target_id in zip(ArtifactKind, TARGET_IDS, strict=True)
            ),
            authorized_knowledge_json=None,
            sealed=False,
            budget_remaining_tokens=1_000,
            timeout_s=10.0,
        )
    )
    validated = validate_critic_bundle(
        result.bundle,
        CritiqueAssignment(
            protocol_version="1.0",
            kind="critique_assignment",
            workspace_id=WORKSPACE_ID,
            session_id=SESSION_ID,
            critic_definition_id=definition.id,
            critic_definition_version=definition.version,
            turn_id=TURN_ID,
            correlation_id=CORRELATION_ID,
            causation_id=CAUSATION_ID,
            round=2,
            target_artifact_ids=TARGET_IDS,
        ),
    )

    assert validated == bundle
    payloads = tuple(
        validate_artifact_payload(ArtifactKind.CRITIQUE, proposal.payload)
        for proposal in validated.artifacts
    )
    assert all(isinstance(payload, CritiquePayload) for payload in payloads)
    target_ids = tuple(
        payload.target_id for payload in payloads if isinstance(payload, CritiquePayload)
    )
    assert target_ids == TARGET_IDS
    assert len(validated.artifacts) == 14
    assert len(ArtifactKind) == 14
    assert result.provider == "mock"
    assert result.model == "critic-fixture"
    assert result.input_tokens == 37
    assert result.output_tokens == 53
    assert len(registry.records) == 1
    assert registry.records[0].agent_def_id == definition.id
