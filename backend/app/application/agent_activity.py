"""Provider-neutral execution of one typed logical-agent turn."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from uuid import UUID

from app.application.llm import LLMCallRunner
from app.domain.agent_activity import AgentTurnInput, AgentTurnResult, ProposalBundle
from app.domain.agent_registry import AgentDefinition, AgentRegistry, AgentStatus, LLMConfiguration
from app.ports.agent_runtime import PinnedAgentDefinition
from app.ports.errors import PermanentPortError
from app.ports.llm import LLMCallTrace, LLMMessage, LLMProvider, LLMRequest, MessageRole
from app.ports.storage import ObjectRef, ObjectStore

__all__ = ["AgentTurnRunner", "ProviderFactory", "RegistryFactory"]

ProviderFactory = Callable[[LLMConfiguration], LLMProvider]
RegistryFactory = Callable[[UUID], AgentRegistry]
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


class AgentTurnRunner:
    """Resolve immutable agent configuration, call LLM, return proposals without committing them."""

    def __init__(
        self,
        registries: RegistryFactory,
        provider_factory: ProviderFactory,
        object_store: ObjectStore,
        *,
        prompt_bucket: str,
        code_version: str,
    ) -> None:
        if not prompt_bucket.strip():
            raise ValueError("prompt_bucket must not be blank")
        self._registries = registries
        self._provider_factory = provider_factory
        self._object_store = object_store
        self._prompt_bucket = prompt_bucket
        self._code_version = code_version

    async def run(self, command: AgentTurnInput) -> AgentTurnResult:
        registry = self._registries(command.workspace_id)
        definition = await registry.get_definition(command.agent_definition_id)
        if definition is None or definition.workspace_id != command.workspace_id:
            raise PermanentPortError(
                "pinned agent definition does not exist", port="agent_activity"
            )
        snapshot = _pinned_definition(command.agent_definition_json)
        if not _definition_matches_snapshot(definition, command, snapshot):
            raise PermanentPortError(
                "durable agent definition does not match the pinned turn snapshot",
                port="agent_activity",
            )
        if definition.status in {AgentStatus.DRAFT, AgentStatus.WITHDRAWN}:
            raise PermanentPortError(
                "pinned agent definition is not runnable", port="agent_activity"
            )
        if definition.llm_config_id is None:
            raise PermanentPortError("pinned agent has no LLM configuration", port="agent_activity")
        configuration = await registry.get_configuration(definition.llm_config_id)
        if (
            configuration is None
            or configuration.workspace_id != command.workspace_id
            or not configuration.is_active
        ):
            raise PermanentPortError(
                "agent LLM configuration is unavailable", port="agent_activity"
            )
        system_prompt = await self._load_prompt(definition.prompt_ref, definition.prompt_hash)
        provider = self._provider_factory(configuration)

        try:
            request = LLMRequest(
                messages=(
                    LLMMessage(MessageRole.SYSTEM, system_prompt),
                    LLMMessage(MessageRole.USER, _turn_prompt(command, snapshot)),
                ),
                model=configuration.model,
                trace=LLMCallTrace(
                    correlation_id=str(command.correlation_id),
                    session_id=str(command.session_id),
                    agent_id=str(command.agent_definition_id),
                    code_version=self._code_version,
                ),
                secret_ref=configuration.secret_ref,
                response_schema=ProposalBundle,
                max_output_tokens=min(command.budget_remaining_tokens, 4096),
                timeout_s=command.timeout_s,
                temperature=0.0,
            )
            response = await LLMCallRunner(provider, registry).generate(
                request,
                workspace_id=command.workspace_id,
                llm_config_id=configuration.id,
                session_id=command.session_id,
                agent_def_id=definition.id,
                call_id=command.turn_id,
            )
            if not isinstance(response.parsed, ProposalBundle):
                raise PermanentPortError(
                    "provider returned no typed proposal bundle", port="agent_activity"
                )
            if response.parsed.turn_id != command.turn_id:
                raise PermanentPortError(
                    "provider returned a proposal for another turn", port="agent_activity"
                )
            if command.round == 1 and not response.parsed.self_reported_limits:
                raise PermanentPortError(
                    "the first agent turn must report at least one limitation",
                    port="agent_activity",
                )
            ref = response.raw_artifact_ref
            return AgentTurnResult(
                turn_id=command.turn_id,
                agent_definition_id=command.agent_definition_id,
                bundle=response.parsed,
                provider=response.provider,
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_usd=response.usage.cost_usd,
                raw_artifact_ref=f"{ref.bucket}/{ref.key}#{ref.digest}",
            )
        finally:
            await provider.close()

    async def _load_prompt(self, prompt_ref: str, prompt_hash: str) -> str:
        if not prompt_ref.strip():
            raise PermanentPortError("pinned agent has no prompt artifact", port="agent_activity")
        if _SHA256.fullmatch(prompt_hash) is None:
            raise PermanentPortError("pinned agent prompt hash is invalid", port="agent_activity")
        body = await self._object_store.get(
            ObjectRef(
                bucket=self._prompt_bucket,
                key=prompt_ref,
                digest=prompt_hash,
                content_type="text/plain; charset=utf-8",
            )
        )
        actual_hash = "sha256:" + hashlib.sha256(body).hexdigest()
        if actual_hash != prompt_hash:
            raise PermanentPortError(
                f"digest mismatch for sealed prompt {self._prompt_bucket}/{prompt_ref}",
                port="agent_activity",
            )
        try:
            prompt = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PermanentPortError(
                "sealed agent prompt is not valid UTF-8", port="agent_activity", cause=exc
            ) from exc
        if not prompt.strip():
            raise PermanentPortError("sealed agent prompt is blank", port="agent_activity")
        return prompt


def _pinned_definition(value: str) -> PinnedAgentDefinition:
    try:
        return PinnedAgentDefinition.model_validate_json(value)
    except ValueError as exc:
        raise PermanentPortError(
            "pinned agent definition snapshot is invalid",
            port="agent_activity",
            cause=exc,
        ) from exc


def _definition_matches_snapshot(
    definition: AgentDefinition,
    command: AgentTurnInput,
    snapshot: PinnedAgentDefinition,
) -> bool:
    return (
        definition.id == command.agent_definition_id == snapshot.id
        and definition.version == command.agent_definition_version == snapshot.version
        and definition.logical_id == snapshot.logical_id
        and definition.name == snapshot.name
        and definition.domain == snapshot.domain
        and definition.role_kind.value == snapshot.role_kind
        and definition.objectives == snapshot.objectives
        and definition.constraints == snapshot.constraints
        and definition.knowledge_ns == snapshot.knowledge_namespace_ids
        and definition.strategy_ref == snapshot.strategy_name
        and definition.strategy_ver == snapshot.strategy_version
        and definition.prompt_ref == snapshot.prompt_ref
        and definition.prompt_hash == snapshot.prompt_hash
    )


def _turn_prompt(command: AgentTurnInput, definition: PinnedAgentDefinition) -> str:
    definition_context = definition.model_dump(mode="json")
    artifact_context = [json.loads(value) for value in command.visible_artifact_json]
    retrieval_context = (
        json.loads(command.authorized_knowledge_json)
        if command.authorized_knowledge_json is not None
        else None
    )
    return (
        f"Return proposal_bundle protocol 1.0 for turn_id {command.turn_id}. "
        f"Session round={command.round}, phase={command.phase.value}, sealed={command.sealed}. "
        f"Problem: {command.problem_statement}\n"
        f"Pinned canonicalizer version: {command.canonicalizer_version}. "
        f"Pinned agent definition: {json.dumps(definition_context, default=str, sort_keys=True)}. "
        f"Session objectives: {list(command.objective_summaries)!r}. "
        f"Session constraints: {list(command.constraint_summaries)!r}. "
        f"Authorized retrieval: {json.dumps(retrieval_context, default=str, sort_keys=True)}. "
        f"Visible prior artifacts: {json.dumps(artifact_context, default=str, sort_keys=True)}. "
        "On the first turn, self_reported_limits must contain at least one honest limitation."
    )
