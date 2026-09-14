"""Provider-independent LLM execution with mandatory durable call accounting."""

from __future__ import annotations

from uuid import UUID

from app.common.ids import uuid7
from app.domain.agent_registry import AgentRegistry, LLMCallRecord
from app.ports.llm import LLMProvider, LLMRequest, LLMResponse

__all__ = ["LLMCallRunner"]


class LLMCallRunner:
    """Execute one generation and persist its normalized usage and trace artifact."""

    def __init__(self, provider: LLMProvider, registry: AgentRegistry) -> None:
        self._provider = provider
        self._registry = registry

    async def generate(
        self,
        request: LLMRequest,
        *,
        workspace_id: UUID,
        llm_config_id: UUID | None = None,
        session_id: UUID | None = None,
        agent_def_id: UUID | None = None,
        call_id: UUID | None = None,
    ) -> LLMResponse:
        response = await self._provider.generate(request)
        ref = response.raw_artifact_ref
        await self._registry.add_call_record(
            LLMCallRecord(
                id=call_id or uuid7(),
                workspace_id=workspace_id,
                session_id=session_id,
                agent_def_id=agent_def_id,
                llm_config_id=llm_config_id,
                provider=response.provider,
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cost_usd=response.usage.cost_usd,
                latency_ms=response.latency_ms,
                finish_reason=response.finish_reason.value,
                retry_attempts=response.retry_attempts,
                raw_artifact_ref=f"{ref.bucket}/{ref.key}#{ref.digest}",
                correlation_id=request.trace.correlation_id,
            )
        )
        return response
