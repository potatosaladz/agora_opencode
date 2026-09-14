"""Strict public request and response contracts for Audit Search."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.ids import parse_id

__all__ = [
    "AuditCompleteness",
    "AuditIntegrity",
    "AuditQueryRequest",
    "AuditQuestion",
    "AuditResponse",
    "Q1Request",
    "Q2Request",
    "Q3Request",
    "Q4Request",
    "Q5Request",
    "Q6Request",
    "Q7Request",
    "Q8Request",
]


class AuditQuestion(StrEnum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    Q5 = "Q5"
    Q6 = "Q6"
    Q7 = "Q7"
    Q8 = "Q8"


class AuditCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AuditIntegrity(StrEnum):
    VERIFIED_UNALTERED = "VERIFIED_UNALTERED"
    ALTERED = "ALTERED"
    NOT_VERIFIABLE = "NOT_VERIFIABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ArtifactQuery(_Strict):
    artifact_id: str

    @field_validator("artifact_id")
    @classmethod
    def valid_artifact_id(cls, value: str) -> str:
        parse_id("artifact", value)
        return value


class Q1Request(_ArtifactQuery):
    question: Literal[AuditQuestion.Q1]
    max_depth: int = Field(default=8, ge=0, le=12)
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None


class Q2Request(_ArtifactQuery):
    question: Literal[AuditQuestion.Q2]


class Q3Request(_Strict):
    question: Literal[AuditQuestion.Q3]
    round: int = Field(ge=0)


class Q4Request(_Strict):
    question: Literal[AuditQuestion.Q4]
    round: int = Field(ge=1)


class Q5Request(_Strict):
    question: Literal[AuditQuestion.Q5]


class Q6Request(_Strict):
    question: Literal[AuditQuestion.Q6]
    round: int = Field(ge=1)


class Q7Request(_Strict):
    question: Literal[AuditQuestion.Q7]
    recommendation_id: str
    limit: int = Field(default=100, ge=1, le=200)
    cursor: str | None = None

    @field_validator("recommendation_id")
    @classmethod
    def valid_recommendation_id(cls, value: str) -> str:
        parse_id("recommendation", value)
        return value


class Q8Request(_Strict):
    question: Literal[AuditQuestion.Q8]


AuditQueryRequest = Annotated[
    Q1Request | Q2Request | Q3Request | Q4Request | Q5Request | Q6Request | Q7Request | Q8Request,
    Field(discriminator="question"),
]


class AuditState(_Strict):
    completeness: AuditCompleteness
    completeness_reasons: tuple[str, ...] = ()
    integrity: AuditIntegrity
    integrity_reasons: tuple[str, ...] = ()


class AuditPagination(_Strict):
    truncated: bool = False
    next_cursor: str | None = None


class Q1Answer(_Strict):
    kind: Literal["ARTIFACT_RATIONALE"]
    artifact_id: str
    provenance: dict[str, Any] | None
    committed_by_event: dict[str, Any] | None
    originating_turn_event: dict[str, Any] | None


class Q2Answer(_Strict):
    kind: Literal["ARTIFACT_REVISION_HISTORY"]
    artifact_id: str
    revisions: tuple[dict[str, Any], ...]


class Q3Answer(_Strict):
    kind: Literal["ROUND_CONTEXT"]
    round: int
    participants: tuple[dict[str, Any], ...]
    turn_events: tuple[dict[str, Any], ...]


class Q4Answer(_Strict):
    kind: Literal["DISSENT_SUPPRESSION_CHECK"]
    consensus_result_id: str | None
    outcome: str | None
    all_persisted_positions_included: bool
    contributions: tuple[dict[str, Any], ...]
    minority_report: tuple[dict[str, Any], ...]


class Q5Answer(_Strict):
    kind: Literal["SESSION_TERMINATION"]
    final_state: str | None
    final_round: int | None
    ended_at: str | None
    last_event: dict[str, Any] | None


class Q6Answer(_Strict):
    kind: Literal["STRATEGY_USAGE"]
    strategy: str | None
    strategy_version: str | None = None
    input_hash: str | None = None
    outcome: str | None = None
    conditions: tuple[str, ...] = ()
    pareto_set: tuple[str, ...] = ()
    created_at: str | None = None
    formula: str | None = None
    weights: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, Any] = Field(default_factory=dict)


class Q7Answer(_Strict):
    kind: Literal["RECOMMENDATION_ACCESS"]
    recommendation_id: str
    recommendation_created_at: str
    boundary: Literal["STRICTLY_BEFORE_RECOMMENDATION_CREATED_AT"]
    entries: tuple[dict[str, Any], ...]


class Q8Answer(_Strict):
    kind: Literal["CHAIN_VERIFICATION"]
    event_count: int
    ledger_valid: bool
    ledger_reason: str | None
    ledger_head_hash: str
    chain_valid: bool | None
    first_invalid_day: str | None
    anchors: tuple[dict[str, Any], ...]


AuditAnswer = Annotated[
    Q1Answer | Q2Answer | Q3Answer | Q4Answer | Q5Answer | Q6Answer | Q7Answer | Q8Answer,
    Field(discriminator="kind"),
]


class AuditData(_Strict):
    question: AuditQuestion
    question_text: str
    parameters: dict[str, Any]
    answer: AuditAnswer
    evidence: tuple[dict[str, Any], ...]
    state: AuditState
    pagination: AuditPagination
    links: dict[str, str]


class AuditMeta(_Strict):
    request_id: str
    schema_version: int
    workspace_id: str


class AuditResponse(_Strict):
    data: AuditData
    meta: AuditMeta
