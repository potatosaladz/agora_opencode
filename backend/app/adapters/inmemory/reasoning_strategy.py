"""Deterministic reasoning strategy for offline tests and replay fixtures."""

from __future__ import annotations

from collections.abc import Callable

from app.ports.agent_runtime import ProposalLike, ReasoningContext, ReasoningStrategy

__all__ = ["DeterministicReasoningStrategy"]


class DeterministicReasoningStrategy[ProposalT: ProposalLike](ReasoningStrategy[ProposalT]):
    def __init__(
        self,
        name: str,
        version: str,
        proposal_factory: Callable[[ReasoningContext], ProposalT],
    ) -> None:
        if not name.strip() or not version.strip():
            raise ValueError("strategy name and version must not be blank")
        self.name = name
        self.version = version
        self._proposal_factory = proposal_factory
        self.contexts: list[ReasoningContext] = []

    async def propose(self, context: ReasoningContext) -> ProposalT:
        self.contexts.append(context)
        return self._proposal_factory(context)
