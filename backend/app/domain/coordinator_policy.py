"""Coordinator-owned mutable membership and durable budget policy contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.agent_registry import AgentDefinition

__all__ = [
    "BudgetCeiling",
    "BudgetUsage",
    "CoordinatorPolicyStore",
    "EffectiveMembershipStore",
    "MembershipIntervention",
    "MembershipInterventionKind",
    "MembershipSnapshot",
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


class MembershipInterventionKind(StrEnum):
    REPLACE = "REPLACE"
    INJECT = "INJECT"


class MembershipIntervention(_FrozenModel):
    event_id: UUID
    workspace_id: UUID
    session_id: UUID
    kind: MembershipInterventionKind
    replaced_agent_definition_id: UUID | None = None
    agent_definition_id: UUID
    effective_round: int = Field(ge=1)
    actor_id: UUID
    correlation_id: UUID
    reason: str = Field(min_length=1)
    recorded_at: datetime

    _recorded_at_utc = field_validator("recorded_at")(_utc)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value

    @model_validator(mode="after")
    def replacement_shape(self) -> MembershipIntervention:
        replacing = self.kind is MembershipInterventionKind.REPLACE
        if replacing != (self.replaced_agent_definition_id is not None):
            raise ValueError("REPLACE requires exactly one replaced agent definition")
        if self.replaced_agent_definition_id == self.agent_definition_id:
            raise ValueError("replacement agent definition must differ")
        return self


class MembershipSnapshot(_FrozenModel):
    workspace_id: UUID
    session_id: UUID
    round: int = Field(ge=1)
    definitions: tuple[AgentDefinition, ...]

    @model_validator(mode="after")
    def one_version_per_logical_agent(self) -> MembershipSnapshot:
        if not self.definitions:
            raise ValueError("session membership must not be empty")
        if any(item.workspace_id != self.workspace_id for item in self.definitions):
            raise ValueError("session membership contains another workspace")
        logical_ids = tuple(item.logical_id for item in self.definitions)
        if len(set(logical_ids)) != len(logical_ids):
            raise ValueError("session membership contains multiple versions of one logical agent")
        return self


class BudgetUsage(_FrozenModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class BudgetCeiling(_FrozenModel):
    max_tokens: int = Field(gt=0)
    max_usd: Decimal = Field(gt=0)


@runtime_checkable
class EffectiveMembershipStore(Protocol):
    """Resolve exact session membership at one effective round."""

    async def membership(
        self, workspace_id: UUID, session_id: UUID, *, round: int
    ) -> MembershipSnapshot: ...


@runtime_checkable
class CoordinatorPolicyStore(EffectiveMembershipStore, Protocol):
    """Caller-transaction-scoped membership and durable usage boundary."""

    async def lock_membership(self, workspace_id: UUID, session_id: UUID) -> None: ...

    async def get_definition(
        self, workspace_id: UUID, agent_definition_id: UUID
    ) -> AgentDefinition | None: ...

    async def add_intervention(self, intervention: MembershipIntervention) -> None: ...

    async def get_intervention(self, event_id: UUID) -> MembershipIntervention | None: ...

    async def session_ceiling(
        self, workspace_id: UUID, session_id: UUID
    ) -> BudgetCeiling | None: ...

    async def session_usage(self, workspace_id: UUID, session_id: UUID) -> BudgetUsage: ...

    async def agent_ceiling(
        self, workspace_id: UUID, agent_definition_id: UUID
    ) -> BudgetCeiling | None: ...

    async def agent_usage(
        self, workspace_id: UUID, session_id: UUID, agent_definition_id: UUID
    ) -> BudgetUsage: ...
