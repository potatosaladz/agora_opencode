"""T6-05 shipped policy-expert catalogue and prompt artifact tests."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.application.policy_experts import (
    POLICY_EXPERT_PROMPT_BUCKET,
    build_policy_expert_catalogue,
    pinned_policy_expert,
    policy_expert_prompts,
    stage_policy_expert_prompts,
)
from app.domain.agent_registry import AgentRoleKind, AgentStatus
from app.ports.storage import ObjectRef
from tests.traceability import req

WORKSPACE_ID = UUID("018f1000-0000-7000-8000-000000000001")
CONFIGURATION_ID = UUID("018f1000-0000-7000-8000-000000000002")
EXPECTED_PROMPT_DIGESTS = {
    "fiscal-policy": "sha256:e993597b9d29c21317a33dd4e20434d2173cbd38be7cc07bdbf54db52df04aea",
    "infrastructure-policy": (
        "sha256:273947b548ff8d7d7cd0073b2cfc046f519e19717313398d8b0db21cd850bce3"
    ),
    "macroeconomic-policy": (
        "sha256:b2860a9128b4e24c141c92b806cd5a2cdd9b75f213201e317831948f50c2218c"
    ),
    "risk-policy": "sha256:d05e57efe5ecd495a6fd6dbf691db836bd6635d92f702abacc7efba0b695c3f8",
    "social-policy": "sha256:35737ca2057a34a5d00ddf8a0f9e63dd55c908270ffb5d17d06778c8b379cfe7",
}


@req("FR-204")
def test_catalogue_has_five_distinct_deterministic_runnable_experts() -> None:
    definitions = build_policy_expert_catalogue(WORKSPACE_ID, CONFIGURATION_ID)

    assert definitions == build_policy_expert_catalogue(WORKSPACE_ID, CONFIGURATION_ID)
    assert len(definitions) == 5
    assert {definition.domain for definition in definitions} == {
        "fiscal-policy",
        "macroeconomic-policy",
        "social-policy",
        "infrastructure-policy",
        "risk-policy",
    }
    assert len({definition.id for definition in definitions}) == 5
    assert len({definition.logical_id for definition in definitions}) == 5
    assert len({definition.objectives for definition in definitions}) == 5
    assert len({definition.constraints[0] for definition in definitions}) == 5
    assert all(definition.version == 1 for definition in definitions)
    assert all(definition.role_kind is AgentRoleKind.DOMAIN_EXPERT for definition in definitions)
    assert all(definition.status is AgentStatus.ACTIVE for definition in definitions)
    assert all(definition.strategy_ref == "evidence-first" for definition in definitions)
    assert all(definition.strategy_ver == "1.0.0" for definition in definitions)
    assert all(definition.llm_config_id == CONFIGURATION_ID for definition in definitions)
    assert all(
        definition.budget == {"max_tokens": 100_000, "max_cost_usd": "25"}
        for definition in definitions
    )


@req("FR-204")
def test_catalogue_ids_are_workspace_scoped_and_snapshot_is_exact() -> None:
    first = build_policy_expert_catalogue(WORKSPACE_ID, CONFIGURATION_ID)[0]
    other_workspace = replace(
        first,
        workspace_id=UUID("018f1000-0000-7000-8000-000000000099"),
    )

    generated_elsewhere = build_policy_expert_catalogue(
        other_workspace.workspace_id, CONFIGURATION_ID
    )[0]

    assert generated_elsewhere.id != first.id
    assert generated_elsewhere.logical_id != first.logical_id
    snapshot = pinned_policy_expert(first)
    assert snapshot.id == first.id
    assert snapshot.logical_id == first.logical_id
    assert snapshot.objectives == first.objectives
    assert snapshot.constraints == first.constraints
    assert snapshot.prompt_ref == first.prompt_ref
    assert snapshot.prompt_hash == first.prompt_hash


@req("FR-204")
async def test_packaged_prompts_are_utf8_digest_pinned_and_staged_exactly() -> None:
    store = InMemoryObjectStore()
    prompts = policy_expert_prompts()
    definitions = build_policy_expert_catalogue(WORKSPACE_ID, CONFIGURATION_ID)

    assert len(prompts) == 5
    assert {prompt.slug: prompt.digest for prompt in prompts} == EXPECTED_PROMPT_DIGESTS
    assert len({prompt.digest for prompt in prompts}) == 5
    assert len({prompt.key for prompt in prompts}) == 5
    assert all(prompt.body.decode("utf-8").strip() for prompt in prompts)
    assert all(b"\r" not in prompt.body for prompt in prompts)
    assert all(prompt.digest.removeprefix("sha256:") in prompt.key for prompt in prompts)
    assert {(definition.prompt_ref, definition.prompt_hash) for definition in definitions} == {
        (prompt.key, prompt.digest) for prompt in prompts
    }

    refs = await stage_policy_expert_prompts(store)
    assert len(refs) == 5
    for prompt, ref in zip(prompts, refs, strict=True):
        assert ref == prompt.object_ref()
        assert await store.get(ref) == prompt.body


@req("FR-204")
async def test_prompt_staging_rejects_blank_bucket() -> None:
    with pytest.raises(ValueError, match="bucket must not be blank"):
        await stage_policy_expert_prompts(InMemoryObjectStore(), bucket=" ")


@req("FR-204")
async def test_prompt_ref_defaults_to_the_activity_bucket() -> None:
    prompt = policy_expert_prompts()[0]
    assert prompt.object_ref() == ObjectRef(
        bucket=POLICY_EXPERT_PROMPT_BUCKET,
        key=prompt.key,
        digest=prompt.digest,
        content_type="text/plain; charset=utf-8",
        size=len(prompt.body),
    )
