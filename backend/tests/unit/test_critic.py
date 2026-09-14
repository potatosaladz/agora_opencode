"""T7-02 shipped Critic definition and prompt artifact tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from uuid import UUID

import pytest

from app.adapters.inmemory.object_store import InMemoryObjectStore
from app.application.critic import (
    CRITIC_PROMPT_BUCKET,
    build_critic_definition,
    critic_prompt,
    pinned_critic,
    stage_critic_prompt,
)
from app.domain.agent_registry import AgentRoleKind, AgentStatus
from app.ports.errors import PermanentPortError
from app.ports.storage import ObjectRef
from tests.traceability import req

WORKSPACE_ID = UUID("018f3000-0000-7000-8000-000000000001")
CONFIGURATION_ID = UUID("018f3000-0000-7000-8000-000000000002")
EXPECTED_DIGEST = "sha256:fbb1da3c35ae800cde3241a6ce74335f4da5ffd70576b7797bc6a2dcd7f4e1e4"


@req("FR-205")
def test_critic_definition_is_deterministic_distinct_and_adversarial() -> None:
    definition = build_critic_definition(WORKSPACE_ID, CONFIGURATION_ID)

    assert definition == build_critic_definition(WORKSPACE_ID, CONFIGURATION_ID)
    assert definition.role_kind is AgentRoleKind.CRITIC
    assert definition.status is AgentStatus.ACTIVE
    assert definition.domain == "cross-cutting-critique"
    assert definition.strategy_ref == "cross-cutting-critique"
    assert definition.strategy_ver == "1.0.0"
    assert definition.llm_config_id == CONFIGURATION_ID
    assert definition.objectives == (
        "Find material defects across every assigned reasoning artifact kind",
        "Preserve explicit unresolved objections without deciding their resolution",
    )
    assert "Adversarial stance" in definition.constraints[0]
    assert definition.prompt_hash == EXPECTED_DIGEST
    assert build_critic_definition(UUID(int=99), CONFIGURATION_ID).id != definition.id


@req("FR-205")
def test_critic_snapshot_is_exact_and_rejects_non_critic_definition() -> None:
    definition = build_critic_definition(WORKSPACE_ID, CONFIGURATION_ID)
    snapshot = pinned_critic(definition)

    assert snapshot.id == definition.id
    assert snapshot.logical_id == definition.logical_id
    assert snapshot.role_kind == AgentRoleKind.CRITIC.value
    assert snapshot.objectives == definition.objectives
    assert snapshot.constraints == definition.constraints
    assert snapshot.prompt_ref == definition.prompt_ref
    assert snapshot.prompt_hash == definition.prompt_hash

    with pytest.raises(ValueError, match="requires a critic definition"):
        pinned_critic(replace(definition, role_kind=AgentRoleKind.DOMAIN_EXPERT))


@req("FR-205")
async def test_critic_prompt_is_utf8_lf_digest_pinned_and_staged_exactly() -> None:
    store = InMemoryObjectStore()
    prompt = critic_prompt()

    assert prompt.digest == EXPECTED_DIGEST
    assert prompt.body.decode("utf-8").strip()
    assert b"\r" not in prompt.body
    assert EXPECTED_DIGEST.removeprefix("sha256:") in prompt.key
    assert b"EVIDENCE_GAP" in prompt.body
    assert b"CRITIQUE artifact proposals" in prompt.body
    assert b"Never commit or resolve artifacts" in prompt.body

    ref = await stage_critic_prompt(store)
    assert ref == prompt.object_ref()
    assert await store.get(ref) == prompt.body


@req("FR-205")
async def test_critic_prompt_ref_defaults_to_activity_bucket_and_blank_bucket_fails() -> None:
    prompt = critic_prompt()
    assert prompt.object_ref() == ObjectRef(
        bucket=CRITIC_PROMPT_BUCKET,
        key=prompt.key,
        digest=prompt.digest,
        content_type="text/plain; charset=utf-8",
        size=len(prompt.body),
    )
    with pytest.raises(ValueError, match="bucket must not be blank"):
        await stage_critic_prompt(InMemoryObjectStore(), bucket=" ")


class _CorruptingStore(InMemoryObjectStore):
    async def put(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> ObjectRef:
        ref = await super().put(bucket, key, body, content_type=content_type, metadata=metadata)
        return ref.model_copy(update={"digest": "sha256:" + "0" * 64})


@req("FR-205")
async def test_critic_prompt_staging_rejects_storage_digest_corruption() -> None:
    with pytest.raises(PermanentPortError, match="stored prompt digest differs"):
        await stage_critic_prompt(_CorruptingStore())
