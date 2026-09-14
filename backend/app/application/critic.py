"""Deterministic shipped catalogue entry for the Phase 7 cross-cutting Critic."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.resources import files
from uuid import UUID, uuid5

from app.domain.agent_registry import AgentDefinition, AgentRoleKind, AgentStatus
from app.ports.agent_runtime import PinnedAgentDefinition
from app.ports.errors import PermanentPortError
from app.ports.storage import ObjectRef, ObjectStore

__all__ = [
    "CRITIC_PROMPT_BUCKET",
    "CriticPrompt",
    "build_critic_definition",
    "critic_prompt",
    "pinned_critic",
    "stage_critic_prompt",
]

CRITIC_PROMPT_BUCKET = "artifacts"
_CRITIC_VERSION = 1
_PROMPT_SHA256 = "fbb1da3c35ae800cde3241a6ce74335f4da5ffd70576b7797bc6a2dcd7f4e1e4"
_STRATEGY_NAME = "cross-cutting-critique"
_STRATEGY_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class CriticPrompt:
    """Exact packaged Critic prompt bytes and content identity."""

    key: str
    body: bytes
    digest: str

    def object_ref(self, bucket: str = CRITIC_PROMPT_BUCKET) -> ObjectRef:
        return ObjectRef(
            bucket=bucket,
            key=self.key,
            digest=self.digest,
            content_type="text/plain; charset=utf-8",
            size=len(self.body),
        )


def critic_prompt() -> CriticPrompt:
    """Load exact UTF-8 Critic prompt bytes and reject content drift."""

    body = files("app.expert_prompts").joinpath(f"critic-v{_CRITIC_VERSION}.txt").read_bytes()
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("shipped Critic prompt is not UTF-8") from exc
    if not text.strip():
        raise RuntimeError("shipped Critic prompt is blank")
    actual_sha256 = hashlib.sha256(body).hexdigest()
    if actual_sha256 != _PROMPT_SHA256:
        raise RuntimeError(f"shipped Critic prompt digest differs: expected {_PROMPT_SHA256}")
    digest = "sha256:" + _PROMPT_SHA256
    return CriticPrompt(
        key=f"prompts/critics/v{_CRITIC_VERSION}/critic-{_PROMPT_SHA256}.txt",
        body=body,
        digest=digest,
    )


# trace: FR-205
def build_critic_definition(workspace_id: UUID, llm_config_id: UUID) -> AgentDefinition:
    """Instantiate one stable workspace-scoped cross-cutting Critic definition."""

    prompt = critic_prompt()
    logical_id = uuid5(workspace_id, "agora:critic:cross-cutting")
    return AgentDefinition(
        id=uuid5(logical_id, f"definition:{_CRITIC_VERSION}"),
        workspace_id=workspace_id,
        logical_id=logical_id,
        version=_CRITIC_VERSION,
        name="Cross-cutting Critic",
        domain="cross-cutting-critique",
        role_kind=AgentRoleKind.CRITIC,
        objectives=(
            "Find material defects across every assigned reasoning artifact kind",
            "Preserve explicit unresolved objections without deciding their resolution",
        ),
        constraints=(
            "Adversarial stance: challenge evidence, logic, models, constraints, alternatives, "
            "uncertainty, causality, and interests",
            "Propose only new OPEN CRITIQUE artifacts against coordinator-assigned targets",
            "Never fabricate identifiers, resolve an artifact, route work, or claim "
            "coordinator authority",
        ),
        strategy_ref=_STRATEGY_NAME,
        strategy_ver=_STRATEGY_VERSION,
        prompt_ref=prompt.key,
        prompt_hash=prompt.digest,
        llm_config_id=llm_config_id,
        budget={"max_tokens": 100_000, "max_cost_usd": "25"},
        status=AgentStatus.ACTIVE,
    )


def pinned_critic(definition: AgentDefinition) -> PinnedAgentDefinition:
    """Create the exact immutable activity snapshot for the shipped Critic."""

    if definition.role_kind is not AgentRoleKind.CRITIC:
        raise ValueError("pinned Critic requires a critic definition")
    return PinnedAgentDefinition(
        id=definition.id,
        logical_id=definition.logical_id,
        version=definition.version,
        name=definition.name,
        domain=definition.domain,
        role_kind=definition.role_kind.value,
        objectives=definition.objectives,
        constraints=definition.constraints,
        knowledge_namespace_ids=definition.knowledge_ns,
        strategy_name=definition.strategy_ref,
        strategy_version=definition.strategy_ver,
        prompt_ref=definition.prompt_ref,
        prompt_hash=definition.prompt_hash,
    )


async def stage_critic_prompt(
    object_store: ObjectStore, *, bucket: str = CRITIC_PROMPT_BUCKET
) -> ObjectRef:
    """Stage exact Critic prompt bytes and reject storage identity corruption."""

    if not bucket.strip():
        raise ValueError("prompt bucket must not be blank")
    prompt = critic_prompt()
    ref = await object_store.put(
        bucket,
        prompt.key,
        prompt.body,
        content_type="text/plain; charset=utf-8",
        metadata={
            "kind": "agent-prompt",
            "catalogue": "critics",
            "catalogue-version": str(_CRITIC_VERSION),
            "critic": "cross-cutting",
        },
    )
    if ref.digest != prompt.digest:
        raise PermanentPortError(
            f"stored prompt digest differs for {bucket}/{prompt.key}", port="object_store"
        )
    return ref
