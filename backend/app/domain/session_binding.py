"""Immutable Phase 3 session/problem binding domain values.

Phase 3 creates a fully bound ``DRAFT``. It deliberately does not model the
workflow lifecycle owned by Phase 4, start Temporal, or resolve references from
persistence. Application services must resolve the referenced rows first and
then construct this aggregate, which enforces the tenant and session affinity
of the complete binding.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.reasoning import ArtifactKind

__all__ = [
    "AgentDefinitionBinding",
    "ConstraintBinding",
    "DraftSessionBinding",
    "ObjectiveBinding",
    "SessionBindingStatus",
    "SessionBudget",
]


# trace: FR-102
def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include an RFC 3339 offset")
    return value.astimezone(UTC)


def _budget_usd(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("max_usd must be a decimal string")  # noqa: TRY004
    if not re.fullmatch(r"(?:0|[1-9]\d{0,9})(?:\.\d{1,2})?", value):
        raise ValueError("max_usd must fit NUMERIC(12,2) without exponent notation")
    amount = Decimal(value)
    if amount <= 0:
        raise ValueError("max_usd must be greater than zero")
    return format(amount.normalize(), "f")


NonEmpty = Annotated[str, Field(strict=True, min_length=1)]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class SessionBindingStatus(StrEnum):
    """The only session state owned by the Phase 3 binding aggregate."""

    DRAFT = "DRAFT"


class SessionBudget(_FrozenModel):
    """Resource ceilings committed with a session."""

    max_rounds: Annotated[int, Field(ge=1, le=50)]
    max_tokens: Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
    max_usd: str
    deadline_at: datetime | None = None

    _canonical_usd = field_validator("max_usd", mode="before")(_budget_usd)
    _deadline_utc = field_validator("deadline_at")(_utc)


class AgentDefinitionBinding(_FrozenModel):
    """A session's pin to one immutable agent-definition version row."""

    workspace_id: UUID
    session_id: UUID
    agent_definition_id: UUID
    logical_id: UUID
    version: Annotated[int, Field(gt=0)]


class ObjectiveBinding(_FrozenModel):
    """A typed reference to an objective artifact owned by this session."""

    workspace_id: UUID
    session_id: UUID
    artifact_id: UUID
    kind: Literal[ArtifactKind.OBJECTIVE] = ArtifactKind.OBJECTIVE


class ConstraintBinding(_FrozenModel):
    """A typed reference to a constraint artifact owned by this session."""

    workspace_id: UUID
    session_id: UUID
    artifact_id: UUID
    kind: Literal[ArtifactKind.CONSTRAINT] = ArtifactKind.CONSTRAINT


class DraftSessionBinding(_FrozenModel):
    """The complete immutable problem binding committed at session creation."""

    id: UUID
    workspace_id: UUID
    status: Literal[SessionBindingStatus.DRAFT] = SessionBindingStatus.DRAFT
    problem_statement: NonEmpty
    agents: tuple[AgentDefinitionBinding, ...]
    objectives: tuple[ObjectiveBinding, ...]
    constraints: tuple[ConstraintBinding, ...]
    budget: SessionBudget
    round: Literal[0] = 0
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    _problem_not_blank = field_validator("problem_statement")(_not_blank)
    _timestamps_utc = field_validator("created_at", "updated_at")(_utc)

    @model_validator(mode="after")
    def complete_affine_binding(self) -> DraftSessionBinding:
        if not self.agents:
            raise ValueError("a session requires at least one agent definition")
        if not self.objectives:
            raise ValueError("a session requires at least one objective")

        agent_ids = tuple(binding.agent_definition_id for binding in self.agents)
        if len(set(agent_ids)) != len(agent_ids):
            raise ValueError("agent definition bindings must be unique")
        logical_ids = tuple(binding.logical_id for binding in self.agents)
        if len(set(logical_ids)) != len(logical_ids):
            raise ValueError("a session cannot bind multiple versions of one logical agent")

        objective_ids = tuple(binding.artifact_id for binding in self.objectives)
        if len(set(objective_ids)) != len(objective_ids):
            raise ValueError("objective bindings must be unique")
        constraint_ids = tuple(binding.artifact_id for binding in self.constraints)
        if len(set(constraint_ids)) != len(constraint_ids):
            raise ValueError("constraint bindings must be unique")
        if set(objective_ids) & set(constraint_ids):
            raise ValueError("an artifact cannot be both an objective and a constraint")

        wrong_workspace = (
            any(binding.workspace_id != self.workspace_id for binding in self.agents)
            or any(binding.workspace_id != self.workspace_id for binding in self.objectives)
            or any(binding.workspace_id != self.workspace_id for binding in self.constraints)
        )
        if wrong_workspace:
            raise ValueError("every binding must belong to the session workspace")
        wrong_session = (
            any(binding.session_id != self.id for binding in self.agents)
            or any(binding.session_id != self.id for binding in self.objectives)
            or any(binding.session_id != self.id for binding in self.constraints)
        )
        if wrong_session:
            raise ValueError("every binding must belong to the session")

        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.budget.deadline_at is not None and self.budget.deadline_at <= self.created_at:
            raise ValueError("deadline_at must be later than created_at")
        return self
