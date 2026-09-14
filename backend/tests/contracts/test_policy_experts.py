"""FR-204 contract: every shipped expert runs through the real mock-backed activity."""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.adapters.llm.mock import MockLLMProvider, MockScenario
from app.application.agent_activity import AgentTurnRunner
from app.application.policy_experts import (
    POLICY_EXPERT_PROMPT_BUCKET,
    build_policy_expert_catalogue,
    pinned_policy_expert,
    stage_policy_expert_prompts,
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
from app.domain.reasoning import ArtifactKind
from app.ports.storage import SecretRef
from tests.traceability import req

WORKSPACE_ID = UUID("018f2000-0000-7000-8000-000000000001")
CONFIGURATION_ID = UUID("018f2000-0000-7000-8000-000000000002")
SESSION_ID = UUID("018f2000-0000-7000-8000-000000000003")
TURN_ID = UUID("018f2000-0000-7000-8000-000000000004")
CORRELATION_ID = UUID("018f2000-0000-7000-8000-000000000005")
CAUSATION_ID = UUID("018f2000-0000-7000-8000-000000000006")


class _CatalogueRegistry:
    def __init__(
        self, definitions: tuple[AgentDefinition, ...], configuration: LLMConfiguration
    ) -> None:
        self.definitions = {definition.id: definition for definition in definitions}
        self.configuration = configuration
        self.records: list[LLMCallRecord] = []

    async def add_configuration(self, configuration: LLMConfiguration) -> None:
        self.configuration = configuration

    async def get_configuration(self, configuration_id: UUID) -> LLMConfiguration | None:
        if configuration_id == self.configuration.id:
            return self.configuration
        return None

    async def put_credential_envelope(
        self, configuration_id: UUID, workspace_id: UUID, envelope: CredentialEnvelope
    ) -> None:
        del configuration_id, workspace_id, envelope

    async def get_credential_envelope(self, configuration_id: UUID) -> CredentialEnvelope | None:
        del configuration_id
        return None

    async def add_definition(self, definition: AgentDefinition) -> None:
        self.definitions[definition.id] = definition

    async def add_definition_version(self, previous_id: UUID, definition: AgentDefinition) -> None:
        del previous_id
        self.definitions[definition.id] = definition

    async def get_definition(self, definition_id: UUID) -> AgentDefinition | None:
        return self.definitions.get(definition_id)

    async def add_call_record(self, record: LLMCallRecord) -> None:
        self.records.append(record)

    async def list_call_records(self) -> tuple[LLMCallRecord, ...]:
        return tuple(self.records)


@req("FR-204")
@pytest.mark.contract
async def test_all_five_experts_produce_schema_valid_deterministic_mock_output() -> None:
    store = InMemoryObjectStore()
    definitions = build_policy_expert_catalogue(WORKSPACE_ID, CONFIGURATION_ID)
    await stage_policy_expert_prompts(store)
    configuration = LLMConfiguration(
        id=CONFIGURATION_ID,
        workspace_id=WORKSPACE_ID,
        name="T6-05 deterministic mock",
        provider_kind=ProviderKind.MOCK,
        base_url="mock://local",
        model="policy-expert-fixture",
        secret_ref=SecretRef(provider="none", name="none"),
    )
    registry = _CatalogueRegistry(definitions, configuration)
    bundle = ProposalBundle(
        protocol_version="1.0",
        kind="proposal_bundle",
        turn_id=TURN_ID,
        artifacts=(
            ArtifactProposal(
                op="propose",
                kind=ArtifactKind.CLAIM,
                payload={
                    "statement": "The option requires domain-specific qualification.",
                    "claim_type": "EVALUATIVE",
                    "direction": "SUPPORTS",
                    "strength": "MODERATE",
                    "supporting_evidence_ids": [],
                    "opposing_evidence_ids": [],
                    "review_status": "PROPOSED",
                },
            ),
        ),
        self_reported_limits=("Fixture output has no external evidence.",),
    )

    def provider_factory(_configuration: LLMConfiguration) -> MockLLMProvider:
        return MockLLMProvider(
            store,
            {
                "policy-expert-fixture": MockScenario(
                    responses=(bundle.model_dump_json(),),
                    input_tokens=23,
                    output_tokens=11,
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
        prompt_bucket=POLICY_EXPERT_PROMPT_BUCKET,
        code_version="t6-05-contract",
    )

    results = []
    for definition in definitions:
        snapshot = pinned_policy_expert(definition)
        results.append(
            await runner.run(
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
                    round=1,
                    phase=AgentTurnPhase.ASSESS,
                    problem_statement="Evaluate a national policy option.",
                    objective_summaries=definition.objectives,
                    constraint_summaries=definition.constraints,
                    visible_artifact_json=(),
                    authorized_knowledge_json=None,
                    sealed=True,
                    budget_remaining_tokens=500,
                    timeout_s=10.0,
                )
            )
        )

    assert len(results) == 5
    assert {result.agent_definition_id for result in results} == {
        definition.id for definition in definitions
    }

    assert all(result.bundle == bundle for result in results)
    assert all(result.provider == "mock" for result in results)
    assert all(result.model == "policy-expert-fixture" for result in results)
    assert all(result.input_tokens == 23 and result.output_tokens == 11 for result in results)
    assert len(registry.records) == 5
    assert {record.agent_def_id for record in registry.records} == {
        definition.id for definition in definitions
    }
