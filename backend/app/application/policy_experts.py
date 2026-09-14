"""Deterministic shipped catalogue for the five Phase 6 policy experts."""

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
    "POLICY_EXPERT_PROMPT_BUCKET",
    "PolicyExpertPrompt",
    "build_policy_expert_catalogue",
    "pinned_policy_expert",
    "policy_expert_prompts",
    "stage_policy_expert_prompts",
]

POLICY_EXPERT_PROMPT_BUCKET = "artifacts"
_CATALOGUE_VERSION = 1
_STRATEGY_NAME = "evidence-first"
_STRATEGY_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class _ExpertSpec:
    slug: str
    name: str
    domain: str
    objectives: tuple[str, ...]
    stance: str
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class PolicyExpertPrompt:
    """Exact packaged bytes and content identity staged for one expert definition."""

    slug: str
    key: str
    body: bytes
    digest: str

    def object_ref(self, bucket: str = POLICY_EXPERT_PROMPT_BUCKET) -> ObjectRef:
        return ObjectRef(
            bucket=bucket,
            key=self.key,
            digest=self.digest,
            content_type="text/plain; charset=utf-8",
            size=len(self.body),
        )


_SPECS = (
    _ExpertSpec(
        slug="fiscal-policy",
        name="Fiscal Policy Analyst",
        domain="fiscal-policy",
        objectives=(
            "Assess financing, fiscal space, debt dynamics, and intertemporal trade-offs",
            "Identify distributional effects across taxpayers and spending beneficiaries",
        ),
        stance="Fiscal sustainability with explicit financing and legal ceilings",
        prompt_sha256="e993597b9d29c21317a33dd4e20434d2173cbd38be7cc07bdbf54db52df04aea",
    ),
    _ExpertSpec(
        slug="macroeconomic-policy",
        name="Macroeconomic Policy Analyst",
        domain="macroeconomic-policy",
        objectives=(
            "Assess output, employment, inflation, productivity, and economy-wide feedbacks",
            "Distinguish short-run demand effects from long-run productive capacity",
        ),
        stance="Macroeconomic stability across plausible policy regimes",
        prompt_sha256="b2860a9128b4e24c141c92b806cd5a2cdd9b75f213201e317831948f50c2218c",
    ),
    _ExpertSpec(
        slug="social-policy",
        name="Social Policy Analyst",
        domain="social-policy",
        objectives=(
            "Assess access, inclusion, household welfare, and effects on vulnerable groups",
            "Disaggregate distributional outcomes and unintended social harms",
        ),
        stance="Equitable outcomes without concealed exclusion or material harm",
        prompt_sha256="35737ca2057a34a5d00ddf8a0f9e63dd55c908270ffb5d17d06778c8b379cfe7",
    ),
    _ExpertSpec(
        slug="infrastructure-policy",
        name="Infrastructure Policy Analyst",
        domain="infrastructure-policy",
        objectives=(
            "Assess lifecycle cost, capacity, resilience, maintenance, and spatial effects",
            "Test delivery sequencing, procurement, dependencies, and operational capacity",
        ),
        stance="Deliverability with realistic lead times and whole-life funding",
        prompt_sha256="273947b548ff8d7d7cd0073b2cfc046f519e19717313398d8b0db21cd850bce3",
    ),
    _ExpertSpec(
        slug="risk-policy",
        name="Risk Policy Analyst",
        domain="risk-policy",
        objectives=(
            "Assess downside scenarios, tail events, correlated failures, and reversibility",
            "Evaluate controls, exposure, residual risk, and asymmetric harms",
        ),
        stance="Precaution proportionate to severity and irreversibility",
        prompt_sha256="d05e57efe5ecd495a6fd6dbf691db836bd6635d92f702abacc7efba0b695c3f8",
    ),
)


def policy_expert_prompts() -> tuple[PolicyExpertPrompt, ...]:
    """Load exact UTF-8 bytes shipped inside the backend package."""

    prompts: list[PolicyExpertPrompt] = []
    package = files("app.expert_prompts")
    for spec in _SPECS:
        body = package.joinpath(f"{spec.slug}-v{_CATALOGUE_VERSION}.txt").read_bytes()
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"shipped prompt for {spec.slug} is not UTF-8") from exc
        if not text.strip():
            raise RuntimeError(f"shipped prompt for {spec.slug} is blank")
        actual_sha256 = hashlib.sha256(body).hexdigest()
        if actual_sha256 != spec.prompt_sha256:
            raise RuntimeError(
                f"shipped prompt digest differs for {spec.slug}: expected {spec.prompt_sha256}"
            )
        digest = "sha256:" + spec.prompt_sha256
        prompts.append(
            PolicyExpertPrompt(
                slug=spec.slug,
                key=(
                    f"prompts/policy-experts/v{_CATALOGUE_VERSION}/"
                    f"{spec.slug}-{digest.removeprefix('sha256:')}.txt"
                ),
                body=body,
                digest=digest,
            )
        )
    return tuple(prompts)


# trace: FR-204
def build_policy_expert_catalogue(
    workspace_id: UUID, llm_config_id: UUID
) -> tuple[AgentDefinition, ...]:
    """Instantiate stable workspace-scoped definition IDs over shipped prompt pins."""

    prompts = {prompt.slug: prompt for prompt in policy_expert_prompts()}
    definitions: list[AgentDefinition] = []
    for spec in _SPECS:
        logical_id = uuid5(workspace_id, f"agora:policy-expert:{spec.slug}")
        prompt = prompts[spec.slug]
        definitions.append(
            AgentDefinition(
                id=uuid5(logical_id, f"definition:{_CATALOGUE_VERSION}"),
                workspace_id=workspace_id,
                logical_id=logical_id,
                version=_CATALOGUE_VERSION,
                name=spec.name,
                domain=spec.domain,
                role_kind=AgentRoleKind.DOMAIN_EXPERT,
                objectives=spec.objectives,
                constraints=(
                    f"Analytical stance: {spec.stance}",
                    "Propose typed artifacts only; never claim coordinator authority",
                    "Never fabricate evidence identifiers; report uncertainty and missing data",
                ),
                strategy_ref=_STRATEGY_NAME,
                strategy_ver=_STRATEGY_VERSION,
                prompt_ref=prompt.key,
                prompt_hash=prompt.digest,
                llm_config_id=llm_config_id,
                budget={"max_tokens": 100_000, "max_cost_usd": "25"},
                status=AgentStatus.ACTIVE,
            )
        )
    return tuple(definitions)


def pinned_policy_expert(definition: AgentDefinition) -> PinnedAgentDefinition:
    """Create the exact immutable activity snapshot for a catalogue definition."""

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


async def stage_policy_expert_prompts(
    object_store: ObjectStore, *, bucket: str = POLICY_EXPERT_PROMPT_BUCKET
) -> tuple[ObjectRef, ...]:
    """Stage all versioned prompt bytes and reject storage identity corruption."""

    if not bucket.strip():
        raise ValueError("prompt bucket must not be blank")
    refs: list[ObjectRef] = []
    for prompt in policy_expert_prompts():
        ref = await object_store.put(
            bucket,
            prompt.key,
            prompt.body,
            content_type="text/plain; charset=utf-8",
            metadata={
                "kind": "agent-prompt",
                "catalogue": "policy-experts",
                "catalogue-version": str(_CATALOGUE_VERSION),
                "expert": prompt.slug,
            },
        )
        if ref.digest != prompt.digest:
            raise PermanentPortError(
                f"stored prompt digest differs for {bucket}/{prompt.key}", port="object_store"
            )
        refs.append(ref)
    return tuple(refs)
